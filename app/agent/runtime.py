import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from app.agent.llm_client import LLMClient, LLMError
from app.agent.memory import Memory
from app.agent.summary import SummaryCompactor
from app.agent.token_budget import estimate_messages_tokens
from app.agent.trace import TraceRecorder
from app.repositories import Repository
from app.tools.registry import ToolRegistry


class AgentRuntime:
    def __init__(
        self,
        repository: Repository,
        llm: LLMClient,
        tools: ToolRegistry,
        memory: Memory,
        max_steps: int = 6,
        summary_compactor: SummaryCompactor = None,
    ):
        self.repository = repository
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_steps = max_steps
        self.summary_compactor = summary_compactor or SummaryCompactor(
            repository, history_limit=memory.history_limit
        )

    def run(self, session_id: str, user_input: str) -> Tuple[str, str]:
        request_started_at = time.perf_counter()
        request_id = str(uuid.uuid4())
        trace = TraceRecorder(self.repository, request_id, session_id)
        total_llm_ms = 0
        total_tool_ms = 0
        total_tool_count = 0

        self.repository.add_message(session_id, "user", user_input)
        memory_result = self.memory.build(session_id, user_input)
        messages = memory_result.messages
        trace.record(0, "memory_recall", output_data=memory_result.trace)
        compaction_scheduled = self.summary_compactor.schedule_if_needed(
            session_id, memory_result.trace
        )
        if compaction_scheduled:
            trace.record(
                0,
                "summary_compaction_scheduled",
                output_data={"mode": "background"},
            )

        for step in range(1, self.max_steps + 1):
            prompt_tokens = estimate_messages_tokens(messages)
            trace.record(
                step,
                "llm_request",
                input_data={
                    "message_count": len(messages),
                    "prompt_tokens_estimated": prompt_tokens,
                },
            )

            llm_started_at = time.perf_counter()
            try:
                assistant_message = self.llm.chat(messages, self.tools.schemas())
            except LLMError as exc:
                llm_ms = self._elapsed_ms(llm_started_at)
                total_llm_ms += llm_ms
                trace.record(
                    step,
                    "llm_error",
                    output_data={"llm_ms": llm_ms},
                    error=str(exc),
                )
                answer = "LLM 调用失败：{}".format(exc)
                self.repository.add_message(session_id, "assistant", answer)
                self._record_request_complete(
                    trace,
                    request_started_at,
                    total_llm_ms,
                    total_tool_ms,
                    total_tool_count,
                    "llm_error",
                )
                return answer, request_id

            llm_ms = self._elapsed_ms(llm_started_at)
            total_llm_ms += llm_ms
            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []
            trace.record(
                step,
                "llm_response",
                output_data={
                    "llm_ms": llm_ms,
                    "tool_call_count": len(tool_calls),
                    "has_final_content": bool(
                        (assistant_message.get("content") or "").strip()
                    ),
                },
            )

            if not tool_calls:
                answer = (assistant_message.get("content") or "").strip()
                if not answer:
                    trace.record(step, "empty_response", error="LLM returned no content")
                    answer = "模型没有返回有效内容，请重试。"
                else:
                    trace.record(step, "final_answer", output_data={"answer": answer})
                self.repository.add_message(session_id, "assistant", answer)
                self._record_request_complete(
                    trace,
                    request_started_at,
                    total_llm_ms,
                    total_tool_ms,
                    total_tool_count,
                    "final_answer",
                )
                return answer, request_id

            tool_messages, tool_ms, tool_count = self._execute_tool_calls(
                tool_calls, session_id, step, trace
            )
            total_tool_ms += tool_ms
            total_tool_count += tool_count
            messages.extend(tool_messages)

        answer = "已达到最大执行步数（{}），任务已停止以避免无限循环。".format(
            self.max_steps
        )
        trace.record(self.max_steps, "max_steps_reached", error=answer)
        self.repository.add_message(session_id, "assistant", answer)
        self._record_request_complete(
            trace,
            request_started_at,
            total_llm_ms,
            total_tool_ms,
            total_tool_count,
            "max_steps_reached",
        )
        return answer, request_id

    def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        session_id: str,
        step: int,
        trace: TraceRecorder,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        parsed_calls = [
            self._parse_tool_call(index, tool_call)
            for index, tool_call in enumerate(tool_calls)
        ]
        parallel_calls = [
            call
            for call in parsed_calls
            if call["arguments_ok"] and self.tools.can_execute_parallel(call["name"])
        ]
        serial_calls = [
            call
            for call in parsed_calls
            if not (call["arguments_ok"] and self.tools.can_execute_parallel(call["name"]))
        ]

        results_by_index: Dict[int, Dict[str, Any]] = {}
        total_tool_ms = 0
        if parallel_calls:
            trace.record(
                step,
                "tool_parallel_start",
                output_data={"count": len(parallel_calls)},
            )
            with ThreadPoolExecutor(max_workers=len(parallel_calls)) as executor:
                futures = {
                    executor.submit(self._execute_single_tool, call, session_id, step): call
                    for call in parallel_calls
                }
                for future, call in futures.items():
                    result = future.result()
                    results_by_index[call["index"]] = result
                    total_tool_ms += result["tool_ms"]

        for call in serial_calls:
            result = self._execute_single_tool(call, session_id, step)
            results_by_index[call["index"]] = result
            total_tool_ms += result["tool_ms"]

        tool_messages = []
        for index in sorted(results_by_index):
            result = results_by_index[index]
            call = result["call"]
            self._record_tool_result(trace, step, result)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["call_id"],
                    "name": call["name"],
                    "content": json.dumps(result["payload"], ensure_ascii=False),
                }
            )
        return tool_messages, total_tool_ms, len(parsed_calls)

    def _parse_tool_call(self, index: int, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        function = tool_call.get("function") or {}
        name = function.get("name", "")
        raw_arguments = function.get("arguments", "{}")
        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must decode to an object")
            return {
                "index": index,
                "call_id": tool_call.get("id") or str(uuid.uuid4()),
                "name": name,
                "arguments": arguments,
                "arguments_ok": True,
                "argument_error": None,
            }
        except (ValueError, TypeError) as exc:
            return {
                "index": index,
                "call_id": tool_call.get("id") or str(uuid.uuid4()),
                "name": name,
                "arguments": {},
                "arguments_ok": False,
                "argument_error": "Invalid JSON arguments: {}".format(exc),
            }

    def _execute_single_tool(
        self,
        call: Dict[str, Any],
        session_id: str,
        step: int,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        if not call["arguments_ok"]:
            return {
                "call": call,
                "ok": False,
                "payload": {"ok": False, "error": call["argument_error"]},
                "tool_ms": self._elapsed_ms(started_at),
                "error": call["argument_error"],
            }
        try:
            output = self.tools.execute(call["name"], call["arguments"], session_id)
            return {
                "call": call,
                "ok": True,
                "payload": {"ok": True, "data": output},
                "tool_ms": self._elapsed_ms(started_at),
                "output": output,
                "error": None,
            }
        except Exception as exc:
            return {
                "call": call,
                "ok": False,
                "payload": {"ok": False, "error": str(exc)},
                "tool_ms": self._elapsed_ms(started_at),
                "error": str(exc),
            }

    def _record_tool_result(
        self,
        trace: TraceRecorder,
        step: int,
        result: Dict[str, Any],
    ) -> None:
        call = result["call"]
        if call["arguments_ok"]:
            trace.record(step, "tool_call", name=call["name"], input_data=call["arguments"])
        if result["ok"]:
            trace.record(
                step,
                "tool_result",
                name=call["name"],
                output_data={"tool_ms": result["tool_ms"], "result": result["output"]},
            )
        else:
            trace.record(
                step,
                "tool_error",
                name=call["name"],
                input_data=call["arguments"] if call["arguments_ok"] else None,
                output_data={"tool_ms": result["tool_ms"]},
                error=result["error"],
            )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def _record_request_complete(
        self,
        trace: TraceRecorder,
        request_started_at: float,
        total_llm_ms: int,
        total_tool_ms: int,
        total_tool_count: int,
        status: str,
    ) -> None:
        trace.record(
            999,
            "request_complete",
            output_data={
                "status": status,
                "total_request_ms": self._elapsed_ms(request_started_at),
                "total_llm_ms": total_llm_ms,
                "total_tool_ms": total_tool_ms,
                "tool_count": total_tool_count,
            },
        )
