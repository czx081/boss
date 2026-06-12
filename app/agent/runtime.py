import json
import uuid
from typing import Any, Dict, List, Tuple

from app.agent.llm_client import LLMClient, LLMError
from app.agent.memory import Memory
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
    ):
        self.repository = repository
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_steps = max_steps

    def run(self, session_id: str, user_input: str) -> Tuple[str, str]:
        request_id = str(uuid.uuid4())
        trace = TraceRecorder(self.repository, request_id, session_id)
        self.repository.add_message(session_id, "user", user_input)
        messages = self.memory.build_messages(session_id)

        for step in range(1, self.max_steps + 1):
            trace.record(step, "llm_request", input_data={"message_count": len(messages)})
            try:
                assistant_message = self.llm.chat(messages, self.tools.schemas())
            except LLMError as exc:
                trace.record(step, "llm_error", error=str(exc))
                answer = "LLM 调用失败：{}".format(exc)
                self.repository.add_message(session_id, "assistant", answer)
                return answer, request_id

            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                answer = (assistant_message.get("content") or "").strip()
                if not answer:
                    trace.record(step, "empty_response", error="LLM returned no content")
                    answer = "模型没有返回有效内容，请重试。"
                else:
                    trace.record(step, "final_answer", output_data={"answer": answer})
                self.repository.add_message(session_id, "assistant", answer)
                return answer, request_id

            for tool_call in tool_calls:
                call_id = tool_call.get("id") or str(uuid.uuid4())
                function = tool_call.get("function") or {}
                name = function.get("name", "")
                raw_arguments = function.get("arguments", "{}")
                try:
                    arguments = json.loads(raw_arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("Arguments must decode to an object")
                except (ValueError, TypeError) as exc:
                    result: Dict[str, Any] = {
                        "ok": False,
                        "error": "Invalid JSON arguments: {}".format(exc),
                    }
                    trace.record(step, "tool_error", name=name, error=result["error"])
                else:
                    trace.record(step, "tool_call", name=name, input_data=arguments)
                    try:
                        output = self.tools.execute(name, arguments, session_id)
                        result = {"ok": True, "data": output}
                        trace.record(step, "tool_result", name=name, output_data=output)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                        trace.record(
                            step,
                            "tool_error",
                            name=name,
                            input_data=arguments,
                            error=str(exc),
                        )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        answer = "已达到最大执行步数（{}），任务已停止以避免无限循环。".format(
            self.max_steps
        )
        trace.record(self.max_steps, "max_steps_reached", error=answer)
        self.repository.add_message(session_id, "assistant", answer)
        return answer, request_id

