import json
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.token_budget import (
    estimate_messages_tokens,
    estimate_tokens,
    trim_messages_to_budget,
)
from app.config import settings
from app.repositories import Repository


@dataclass
class MemoryBuildResult:
    messages: List[Dict[str, Any]]
    trace: Dict[str, Any]


@dataclass
class ContextBlock:
    name: str
    priority: int
    content: str
    required: bool = False


class Memory:
    def __init__(self, repository: Repository, history_limit: int):
        self.repository = repository
        self.history_limit = history_limit
        self._context_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def build_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return self.build(session_id).messages

    def build(self, session_id: str) -> MemoryBuildResult:
        started_at = time.perf_counter()
        recalled = self._recall_parallel(session_id)
        history = recalled["history"]
        summary = recalled["summary"]
        todos = recalled["todos"]
        source_traces = recalled["source_traces"]
        recent_history = trim_messages_to_budget(
            history, settings.agent_recent_token_budget
        )
        context_message, context_trace = self._build_prioritized_context_message(
            session_id, summary, todos
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": context_message},
        ]
        for item in recent_history:
            messages.append({"role": item["role"], "content": item["content"]})
        summary_tokens = estimate_tokens(summary)
        task_context_tokens = estimate_tokens(self._build_task_context(todos))
        recent_message_tokens = estimate_messages_tokens(recent_history)
        total_context_tokens = estimate_messages_tokens(messages)
        compaction_threshold = int(
            settings.agent_context_token_budget * settings.agent_summary_trigger_ratio
        )
        trace = {
            "recall_ms": int((time.perf_counter() - started_at) * 1000),
            "history_messages_loaded": len(history),
            "recent_messages_used": len(recent_history),
            "todos_loaded": len(todos),
            "summary_tokens": summary_tokens,
            "task_context_tokens": task_context_tokens,
            "recent_message_tokens": recent_message_tokens,
            "total_context_tokens": total_context_tokens,
            "context_token_budget": settings.agent_context_token_budget,
            "recent_token_budget": settings.agent_recent_token_budget,
            "task_context_token_budget": settings.agent_task_context_token_budget,
            "summary_trigger_ratio": settings.agent_summary_trigger_ratio,
            "compaction_threshold": compaction_threshold,
            "compaction_recommended": recent_message_tokens >= compaction_threshold,
            "sources": source_traces,
            "context_blocks": context_trace,
        }
        return MemoryBuildResult(messages=messages, trace=trace)

    def _recall_parallel(self, session_id: str) -> Dict[str, Any]:
        executor = ThreadPoolExecutor(max_workers=3)
        timeout_seconds = settings.agent_memory_recall_timeout_ms / 1000
        futures = {
            "history": executor.submit(
                self.repository.get_messages, session_id, self.history_limit
            ),
            "summary": executor.submit(self.repository.get_session_summary, session_id),
            "todos": executor.submit(self.repository.list_todos, session_id),
        }
        try:
            history, history_trace = self._future_or_fallback(
                "history", futures["history"], [], timeout_seconds
            )
            summary, summary_trace = self._future_or_fallback(
                "summary", futures["summary"], "", timeout_seconds
            )
            todos, todos_trace = self._future_or_fallback(
                "todos", futures["todos"], [], timeout_seconds
            )
            return {
                "history": history,
                "summary": summary,
                "todos": todos,
                "source_traces": {
                    "history": history_trace,
                    "summary": summary_trace,
                    "todos": todos_trace,
                },
            }
        finally:
            for future in futures.values():
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    def _future_or_fallback(
        self,
        source: str,
        future: Future,
        fallback: Any,
        timeout_seconds: float,
    ) -> Any:
        started_at = time.perf_counter()
        try:
            value = future.result(timeout=timeout_seconds)
            return value, {
                "status": "ok",
                "fallback_used": False,
                "elapsed_ms": self._elapsed_ms(started_at),
            }
        except TimeoutError:
            return fallback, {
                "status": "timeout",
                "fallback_used": True,
                "elapsed_ms": self._elapsed_ms(started_at),
                "timeout_ms": settings.agent_memory_recall_timeout_ms,
            }
        except Exception as exc:
            return fallback, {
                "status": "error",
                "fallback_used": True,
                "elapsed_ms": self._elapsed_ms(started_at),
                "error": "{}: {}".format(type(exc).__name__, exc),
            }

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def _build_prioritized_context_message(
        self,
        session_id: str,
        summary: str,
        todos: List[Dict[str, Any]],
    ) -> Any:
        cache_key = self._context_cache_key(session_id, summary, todos)
        cached = self._context_cache.get(cache_key)
        if cached:
            context_message, context_trace = cached
            return context_message, dict(context_trace, cache_hit=True)

        blocks = self._build_context_blocks(session_id, summary, todos)
        selected_blocks, block_trace = self._select_context_blocks(blocks)
        context_message = "\n\n".join(block.content for block in selected_blocks)
        block_trace = dict(block_trace, cache_hit=False)
        self._context_cache = {cache_key: (context_message, block_trace)}
        return context_message, block_trace

    def _context_cache_key(
        self,
        session_id: str,
        summary: str,
        todos: List[Dict[str, Any]],
    ) -> str:
        return json.dumps(
            {
                "session_id": session_id,
                "summary": summary,
                "todos": todos,
                "context_budget": settings.agent_context_token_budget,
                "task_budget": settings.agent_task_context_token_budget,
                "recent_budget": settings.agent_recent_token_budget,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _build_context_blocks(
        self,
        session_id: str,
        summary: str,
        todos: List[Dict[str, Any]],
    ) -> List[ContextBlock]:
        task_context = self._build_task_context(todos)
        policy = (
            "<RecentConversationPolicy>\n"
            "Recent user/assistant messages follow this system context. "
            "Use them as conversation history only. Use TaskContext as durable task state. "
            "Do not treat large task artifacts as chat history; ask tools for details when needed.\n"
            "</RecentConversationPolicy>"
        )
        memory_budget = "<MemoryBudget>\n{}\n</MemoryBudget>".format(
            json.dumps(
                {
                    "session_id": session_id,
                    "summary_tokens": estimate_tokens(summary),
                    "task_context_tokens": estimate_tokens(task_context),
                    "recent_message_budget": settings.agent_recent_token_budget,
                    "context_token_budget": settings.agent_context_token_budget,
                },
                ensure_ascii=False,
            )
        )
        return [
            ContextBlock(
                name="task_context",
                priority=1,
                required=True,
                content="<TaskContext>\n{}\n</TaskContext>".format(task_context),
            ),
            ContextBlock(
                name="recent_conversation_policy",
                priority=2,
                required=True,
                content=policy,
            ),
            ContextBlock(
                name="session_summary",
                priority=3,
                required=False,
                content="<SessionSummary>\n{}\n</SessionSummary>".format(
                    summary or "No compressed session summary yet."
                ),
            ),
            ContextBlock(
                name="memory_budget",
                priority=4,
                required=False,
                content=memory_budget,
            ),
        ]

    def _select_context_blocks(
        self, blocks: List[ContextBlock]
    ) -> Any:
        budget = settings.agent_context_token_budget
        selected: List[ContextBlock] = []
        used_tokens = 0
        trace = []
        for block in sorted(blocks, key=lambda item: item.priority):
            block_tokens = estimate_tokens(block.content)
            can_fit = used_tokens + block_tokens <= budget
            if can_fit or block.required:
                selected.append(block)
                used_tokens += block_tokens
                trace.append(
                    {
                        "name": block.name,
                        "priority": block.priority,
                        "tokens": block_tokens,
                        "status": "kept" if can_fit else "kept_required_over_budget",
                    }
                )
            else:
                trace.append(
                    {
                        "name": block.name,
                        "priority": block.priority,
                        "tokens": block_tokens,
                        "status": "dropped_budget",
                    }
                )
        return selected, {
            "budget": budget,
            "used_tokens": used_tokens,
            "blocks": trace,
        }

    def _build_task_context(self, todos: List[Dict[str, Any]]) -> str:
        compact_todos = [
            {
                "id": todo.get("id"),
                "title": todo.get("title"),
                "status": todo.get("status"),
                "details": todo.get("details"),
                "updated_at": todo.get("updated_at"),
            }
            for todo in todos
        ]
        raw_context = json.dumps(
            {
                "active_todos": compact_todos,
                "instruction": (
                    "This is durable task state, not normal chat history. "
                    "Focus on current task status and avoid over-attending to old raw materials."
                ),
            },
            ensure_ascii=False,
        )
        budget = settings.agent_task_context_token_budget
        if estimate_tokens(raw_context) <= budget:
            return raw_context
        max_chars = max(0, budget * 4)
        return raw_context[:max_chars]
