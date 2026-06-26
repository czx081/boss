import copy
import json
import time
import unittest
from pathlib import Path
from uuid import uuid4

from app.agent.llm_client import LLMError
from app.agent.memory import Memory
from app.agent.runtime import AgentRuntime
from app.config import settings
from app.database import init_db
from app.repositories import Repository
from app.tools.registry import ToolRegistry


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


class FakeSummaryCompactor:
    def __init__(self, should_schedule=False):
        self.should_schedule = should_schedule
        self.calls = []

    def schedule_if_needed(self, session_id, memory_trace):
        self.calls.append((session_id, memory_trace))
        return self.should_schedule


def use_test_database(name):
    path = Path("data") / "test-dbs" / "{}-{}.db".format(name, uuid4().hex)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def configure_test_database(name):
    original_path = settings.database_path
    object.__setattr__(settings, "database_path", use_test_database(name))
    init_db()
    return original_path


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.original_path = configure_test_database("runtime")

    def tearDown(self):
        object.__setattr__(settings, "database_path", self.original_path)

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

        traces = repository.get_traces(request_id)
        events = [item["event"] for item in traces]
        self.assertEqual(events[0], "memory_recall")
        self.assertIn("llm_response", events)
        self.assertIn("tool_call", events)
        self.assertIn("tool_result", events)
        self.assertIn("final_answer", events)
        self.assertEqual(events[-1], "request_complete")

        llm_request = next(item for item in traces if item["event"] == "llm_request")
        self.assertIn("prompt_tokens_estimated", llm_request["input"])

        llm_response = next(item for item in traces if item["event"] == "llm_response")
        self.assertIn("llm_ms", llm_response["output"])

        tool_result = next(item for item in traces if item["event"] == "tool_result")
        self.assertIn("tool_ms", tool_result["output"])
        self.assertEqual(tool_result["output"]["result"]["result"], 42)

        complete = traces[-1]["output"]
        self.assertEqual(complete["status"], "final_answer")
        self.assertIn("total_request_ms", complete)
        self.assertIn("total_llm_ms", complete)
        self.assertIn("total_tool_ms", complete)
        self.assertEqual(complete["tool_count"], 1)

    def test_runtime_executes_parallel_readonly_tools(self):
        repository = Repository()
        session_id = repository.create_session("parallel")
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
                                "arguments": json.dumps({"expression": "1 + 1"}),
                            },
                        },
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "weather",
                                "arguments": json.dumps({"city": "上海"}),
                            },
                        },
                    ],
                },
                {"role": "assistant", "content": "并行工具完成。"},
            ]
        )
        tools = ToolRegistry(repository)

        def slow_calculator(expression):
            time.sleep(0.2)
            return {"expression": expression, "result": 2}

        def slow_weather(city):
            time.sleep(0.2)
            return {"city": city, "condition": "晴"}

        tools._tools["calculator"].handler = slow_calculator
        tools._tools["weather"].handler = slow_weather
        runtime = AgentRuntime(repository, llm, tools, Memory(repository, 20), max_steps=4)

        started_at = time.perf_counter()
        answer, request_id = runtime.run(session_id, "同时计算并查天气")
        elapsed = time.perf_counter() - started_at

        self.assertEqual(answer, "并行工具完成。")
        self.assertLess(elapsed, 0.35)
        self.assertEqual(llm.calls[1][-2]["name"], "calculator")
        self.assertEqual(llm.calls[1][-1]["name"], "weather")
        traces = repository.get_traces(request_id)
        events = [item["event"] for item in traces]
        self.assertIn("tool_parallel_start", events)
        self.assertEqual(traces[-1]["output"]["tool_count"], 2)

    def test_todo_tool_is_not_parallel_safe(self):
        repository = Repository()
        tools = ToolRegistry(repository)

        self.assertFalse(tools.can_execute_parallel("todo"))
        self.assertTrue(tools.can_execute_parallel("calculator"))

    def test_runtime_schedules_background_summary_compaction(self):
        repository = Repository()
        session_id = repository.create_session("compact")
        compactor = FakeSummaryCompactor(should_schedule=True)
        runtime = AgentRuntime(
            repository,
            FakeLLM([{"role": "assistant", "content": "完成。"}]),
            ToolRegistry(repository),
            Memory(repository, 20),
            max_steps=2,
            summary_compactor=compactor,
        )

        answer, request_id = runtime.run(session_id, "需要压缩吗")

        self.assertEqual(answer, "完成。")
        self.assertEqual(len(compactor.calls), 1)
        events = [item["event"] for item in repository.get_traces(request_id)]
        self.assertIn("summary_compaction_scheduled", events)

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
        traces = repository.get_traces(request_id)
        events = [item["event"] for item in traces]
        self.assertIn("max_steps_reached", events)
        self.assertEqual(events[-1], "request_complete")
        self.assertEqual(traces[-1]["output"]["status"], "max_steps_reached")

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
        events = [item["event"] for item in traces]
        self.assertIn("llm_error", events)
        self.assertEqual(events[-1], "request_complete")
        llm_error = next(item for item in traces if item["event"] == "llm_error")
        self.assertEqual(llm_error["error"], "test timeout")
        self.assertIn("llm_ms", llm_error["output"])
        self.assertEqual(traces[-1]["output"]["status"], "llm_error")

    def test_memory_recalls_todos_before_current_conversation(self):
        repository = Repository()
        session_id = repository.create_session("task")
        repository.create_todo(session_id, "准备演示")
        repository.update_session_summary(session_id, "用户正在准备 Agent 项目面试。")
        repository.add_message(session_id, "user", "进度如何？")

        messages = Memory(repository, 20).build_messages(session_id)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("准备演示", messages[1]["content"])
        self.assertIn("用户正在准备 Agent 项目面试。", messages[1]["content"])
        self.assertIn("<TaskContext>", messages[1]["content"])
        self.assertEqual(messages[-1]["content"], "进度如何？")


if __name__ == "__main__":
    unittest.main()
