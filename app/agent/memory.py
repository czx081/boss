import json
import hashlib
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


@dataclass
class RecallPlan:
    intent: str
    history: bool = True
    summary: bool = True
    todos: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "sources": {
                "history": self.history,
                "summary": self.summary,
                "todos": self.todos,
            },
        }


class Memory:
    def __init__(self, repository: Repository, history_limit: int):
        self.repository = repository
        self.history_limit = history_limit
        self._context_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        self._slow_memory_cache: Dict[str, Dict[str, Any]] = {}

    def build_messages(
        self, session_id: str, user_input: str = ""
    ) -> List[Dict[str, Any]]:
        return self.build(session_id, user_input).messages

    def build(self, session_id: str, user_input: str = "") -> MemoryBuildResult:
        started_at = time.perf_counter()
        recall_plan = self._build_recall_plan(user_input)
        recalled = self._recall_parallel(session_id, recall_plan)
        history = recalled["history"]
        summary = recalled["summary"]
        todos = recalled["todos"]
        source_traces = recalled["source_traces"]
        recent_history = trim_messages_to_budget(
            history, settings.agent_recent_token_budget
        )
        cache_versions = self._build_cache_versions(summary, todos, recent_history)
        context_message, context_trace = self._build_prioritized_context_message(
            session_id, summary, todos, cache_versions
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
            "recall_plan": recall_plan.as_dict(),
            "recall_strategy": recalled["recall_strategy"],
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
            "cache_versions": cache_versions,
            "context_blocks": context_trace,
        }
        return MemoryBuildResult(messages=messages, trace=trace)

    def _build_recall_plan(self, user_input: str) -> RecallPlan:
        text = (user_input or "").lower()
        if not text:
            return RecallPlan(intent="default_full")

        task_keywords = [
            "任务",
            "待办",
            "todo",
            "进度",
            "完成",
            "进行中",
            "刚才那个任务",
            "那个任务",
        ]
        history_keywords = [
            "之前",
            "上次",
            "刚才",
            "聊过",
            "说过",
            "总结",
            "回顾",
            "记得",
        ]
        simple_tool_keywords = ["计算", "天气", "搜索", "查询"]
        task_summary_keywords = ["总结任务", "回顾任务", "之前聊的任务", "上次聊的任务"]
        has_task_intent = any(keyword in text for keyword in task_keywords)
        has_history_intent = any(keyword in text for keyword in history_keywords)
        has_simple_tool_intent = any(keyword in text for keyword in simple_tool_keywords)
        has_task_summary_intent = any(
            keyword in text for keyword in task_summary_keywords
        )

        if has_task_intent:
            return RecallPlan(intent="task_related", summary=has_task_summary_intent)
        if has_history_intent:
            return RecallPlan(intent="history_related", todos=False)
        if has_simple_tool_intent:
            return RecallPlan(intent="simple_tool", summary=False, todos=False)
        return RecallPlan(intent="default_light", summary=False)

    def _recall_parallel(
        self, session_id: str, recall_plan: RecallPlan
    ) -> Dict[str, Any]:
        executor = ThreadPoolExecutor(max_workers=3)
        timeout_seconds = settings.agent_memory_recall_timeout_ms / 1000
        slow_cache = self._slow_memory_cache.get(session_id, {})
        futures = {}
        if recall_plan.history:
            futures["history"] = executor.submit(
                self.repository.get_messages, session_id, self.history_limit
            )
        if recall_plan.summary:
            futures["summary"] = executor.submit(
                self.repository.get_session_summary, session_id
            )
        if recall_plan.todos:
            futures["todos"] = executor.submit(self.repository.list_todos, session_id)
        try:
            history, history_trace = self._recall_selected_source(
                "history",
                futures,
                [],
                timeout_seconds,
                selected=recall_plan.history,
            )
            summary, summary_trace = self._recall_selected_source(
                "summary",
                futures,
                slow_cache.get("summary", ""),
                timeout_seconds,
                selected=recall_plan.summary,
            )
            todos, todos_trace = self._recall_selected_source(
                "todos",
                futures,
                [],
                timeout_seconds,
                selected=recall_plan.todos,
            )
            if summary_trace["status"] == "ok":
                self._slow_memory_cache[session_id] = {
                    **slow_cache,
                    "summary": summary,
                }
            summary_trace = {
                **summary_trace,
                "cache_fallback_available": bool(slow_cache.get("summary")),
            }
            return {
                "history": history,
                "summary": summary,
                "todos": todos,
                "recall_strategy": {
                    "fast_path": ["history", "todos"],
                    "slow_path": ["summary"],
                    "slow_path_policy": (
                        "Slow memory is requested in parallel. If it times out, "
                        "use cached summary or an empty summary so the user path can continue."
                    ),
                },
                "source_traces": {
                    "history": {**history_trace, "path": "fast"},
                    "summary": {**summary_trace, "path": "slow"},
                    "todos": {**todos_trace, "path": "fast"},
                },
            }
        finally:
            for future in futures.values():
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    def _recall_selected_source(
        self,
        source: str,
        futures: Dict[str, Future],
        fallback: Any,
        timeout_seconds: float,
        selected: bool,
    ) -> Any:
        if not selected:
            return fallback, {
                "status": "skipped",
                "fallback_used": False,
                "elapsed_ms": 0,
                "skip_reason": "not_needed_for_current_intent",
            }
        return self._future_or_fallback(
            source, futures[source], fallback, timeout_seconds
        )

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
        cache_versions: Dict[str, Any],
    ) -> Any:
        cache_key = self._context_cache_key(session_id, cache_versions)
        cached = self._context_cache.get(cache_key)
        if cached:
            context_message, context_trace = cached
            return context_message, dict(
                context_trace,
                cache_hit=True,
                cache_key_strategy="source_versions",
                versions=cache_versions,
            )

        blocks = self._build_context_blocks(session_id, summary, todos)
        selected_blocks, block_trace = self._select_context_blocks(blocks)
        context_message = "\n\n".join(block.content for block in selected_blocks)
        block_trace = dict(
            block_trace,
            cache_hit=False,
            cache_key_strategy="source_versions",
            versions=cache_versions,
        )
        self._context_cache = {cache_key: (context_message, block_trace)}
        return context_message, block_trace

    def _context_cache_key(
        self,
        session_id: str,
        cache_versions: Dict[str, Any],
    ) -> str:
        return json.dumps(
            {
                "session_id": session_id,
                "versions": cache_versions,
                "context_budget": settings.agent_context_token_budget,
                "task_budget": settings.agent_task_context_token_budget,
                "recent_budget": settings.agent_recent_token_budget,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _build_cache_versions(
        self,
        summary: str,
        todos: List[Dict[str, Any]],
        recent_history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "summary_version": self._text_fingerprint(summary),
            "todo_version": self._json_fingerprint(self._todo_version_payload(todos)),
            "latest_message_version": self._json_fingerprint(
                recent_history[-1] if recent_history else {}
            ),
        }

    def _todo_version_payload(self, todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "id": todo.get("id"),
                "title": todo.get("title"),
                "status": todo.get("status"),
                "details": todo.get("details"),
                "updated_at": todo.get("updated_at"),
            }
            for todo in todos
        ]

    def _text_fingerprint(self, value: str) -> str:
        return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]

    def _json_fingerprint(self, value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return self._text_fingerprint(payload)

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
        current_step = self._build_current_step(compact_todos)
        raw_context = json.dumps(
            {
                "current_step": current_step,
                "active_todos": compact_todos,
                "instruction": (
                    "This is durable task state, not normal chat history. "
                    "First follow current_step. Focus on the current phase and next_action. "
                    "Do not over-attend to old raw materials or jump to later phases unless the user asks."
                ),
            },
            ensure_ascii=False,
        )
        budget = settings.agent_task_context_token_budget
        if estimate_tokens(raw_context) <= budget:
            return raw_context
        max_chars = max(0, budget * 4)
        return raw_context[:max_chars]

    def _build_current_step(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        current_task = self._select_current_task(todos)
        if not current_task:
            return {
                "task_id": None,
                "task_title": None,
                "phase": "no_active_task",
                "next_action": "Answer the user directly or ask a clarifying question if the task is unclear.",
                "avoid": "Do not invent a task state that is not present in TaskContext.",
            }

        status = current_task.get("status") or "pending"
        phase_by_status = {
            "pending": "not_started",
            "in_progress": "working",
            "completed": "done",
            "cancelled": "cancelled",
        }
        next_action_by_status = {
            "pending": "Confirm the task goal and start from the first concrete step.",
            "in_progress": "Continue the current task from its latest known state.",
            "completed": "Report completion or ask whether the user wants a follow-up task.",
            "cancelled": "Do not continue this task unless the user explicitly reopens it.",
        }
        return {
            "task_id": current_task.get("id"),
            "task_title": current_task.get("title"),
            "phase": phase_by_status.get(status, status),
            "status": status,
            "next_action": next_action_by_status.get(
                status, "Use the task status to decide the next concrete step."
            ),
            "avoid": (
                "Do not treat raw research, old details, or completed steps as the current objective. "
                "Keep attention on this current_step."
            ),
        }

    def _select_current_task(
        self, todos: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        for status in ("in_progress", "pending", "completed", "cancelled"):
            for todo in todos:
                if todo.get("status") == status:
                    return todo
        return todos[0] if todos else {}
