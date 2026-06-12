import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.agent.llm_client import LLMError
from app.agent.memory import Memory
from app.agent.runtime import AgentRuntime
from app.database import init_db
from app.repositories import Repository
from app.tools.registry import ToolRegistry
from app.config import settings


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        return self.responses.pop(0)


class FailingLLM:
    def chat(self, messages, tools):
        raise LLMError("test timeout")


def configure_temp_database(directory):
    original_path = settings.database_path
    object.__setattr__(
        settings, "database_path", str(Path(directory) / "runtime.db")
    )
    init_db()
    return original_path


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = configure_temp_database(self.temp_dir.name)

    def tearDown(self):
        object.__setattr__(settings, "database_path", self.original_path)
        self.temp_dir.cleanup()

    def test_runtime_executes_tool_then_returns_answer(self):
        repository = Repository()
        session_id = repository.create_session("calculate")
        llm = FakeLLM(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": json.dumps({"expression": "6 * 7"}),
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": "答案是 42。"},
            ]
        )
        runtime = AgentRuntime(
            repository,
            llm,
            ToolRegistry(repository),
            Memory(repository, 20),
            max_steps=4,
        )

        answer, request_id = runtime.run(session_id, "计算 6 * 7")

        self.assertEqual(answer, "答案是 42。")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[1][-1]["role"], "tool")
        self.assertIn('"result": 42', llm.calls[1][-1]["content"])
        events = [item["event"] for item in repository.get_traces(request_id)]
        self.assertIn("tool_call", events)
        self.assertIn("tool_result", events)
        self.assertIn("final_answer", events)

    def test_runtime_stops_at_max_steps(self):
        repository = Repository()
        session_id = repository.create_session("loop")
        repeated_call = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-loop",
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "arguments": json.dumps({"city": "上海"}),
                    },
                }
            ],
        }
        runtime = AgentRuntime(
            repository,
            FakeLLM([repeated_call, repeated_call]),
            ToolRegistry(repository),
            Memory(repository, 20),
            max_steps=2,
        )

        answer, request_id = runtime.run(session_id, "不断查询天气")

        self.assertIn("最大执行步数", answer)
        events = [item["event"] for item in repository.get_traces(request_id)]
        self.assertEqual(events[-1], "max_steps_reached")

    def test_runtime_returns_readable_llm_error(self):
        repository = Repository()
        session_id = repository.create_session("failure")
        runtime = AgentRuntime(
            repository,
            FailingLLM(),
            ToolRegistry(repository),
            Memory(repository, 20),
            max_steps=2,
        )

        answer, request_id = runtime.run(session_id, "hello")

        self.assertIn("LLM 调用失败", answer)
        traces = repository.get_traces(request_id)
        self.assertEqual(traces[-1]["event"], "llm_error")
        self.assertEqual(traces[-1]["error"], "test timeout")

    def test_memory_recalls_todos_before_current_conversation(self):
        repository = Repository()
        session_id = repository.create_session("task")
        repository.create_todo(session_id, "准备演示")
        repository.add_message(session_id, "user", "进度如何？")

        messages = Memory(repository, 20).build_messages(session_id)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("准备演示", messages[1]["content"])
        self.assertEqual(messages[-1]["content"], "进度如何？")


if __name__ == "__main__":
    unittest.main()
