import time
import unittest

from app.agent.memory import Memory
from app.config import settings


class FakeRepository:
    def __init__(self):
        self.calls = []

    def get_messages(self, session_id, limit):
        self.calls.append(("get_messages", session_id, limit))
        time.sleep(0.02)
        return [{"role": "user", "content": "hello"}]

    def get_session_summary(self, session_id):
        self.calls.append(("get_session_summary", session_id))
        time.sleep(0.02)
        return "summary text"

    def list_todos(self, session_id):
        self.calls.append(("list_todos", session_id))
        time.sleep(0.02)
        return [{"id": 1, "title": "demo", "status": "pending"}]


class SlowSummaryRepository(FakeRepository):
    def get_session_summary(self, session_id):
        self.calls.append(("get_session_summary", session_id))
        time.sleep(0.6)
        return "late summary"


class MultiTodoRepository(FakeRepository):
    def list_todos(self, session_id):
        self.calls.append(("list_todos", session_id))
        return [
            {
                "id": 3,
                "title": "completed task",
                "status": "completed",
                "details": "",
            },
            {
                "id": 2,
                "title": "make product research PPT",
                "status": "in_progress",
                "details": "research collected; next organize key points",
            },
            {
                "id": 1,
                "title": "pending task",
                "status": "pending",
                "details": "",
            },
        ]


class EmptyTodoRepository(FakeRepository):
    def list_todos(self, session_id):
        self.calls.append(("list_todos", session_id))
        return []


class ChangingHistoryRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.message = "hello"

    def get_messages(self, session_id, limit):
        self.calls.append(("get_messages", session_id, limit))
        return [{"role": "user", "content": self.message}]


class MemoryTests(unittest.TestCase):
    def test_build_messages_recalls_summary_history_and_todos(self):
        repository = FakeRepository()

        messages = Memory(repository, history_limit=20).build_messages("session-1")

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("<SessionSummary>", messages[1]["content"])
        self.assertIn("summary text", messages[1]["content"])
        self.assertIn("<TaskContext>", messages[1]["content"])
        self.assertIn("demo", messages[1]["content"])
        self.assertIn("<RecentConversationPolicy>", messages[1]["content"])
        self.assertIn("<MemoryBudget>", messages[1]["content"])
        self.assertEqual(messages[-1]["content"], "hello")
        self.assertIn(("get_messages", "session-1", 20), repository.calls)
        self.assertIn(("get_session_summary", "session-1"), repository.calls)
        self.assertIn(("list_todos", "session-1"), repository.calls)

    def test_build_returns_memory_trace(self):
        repository = FakeRepository()

        result = Memory(repository, history_limit=20).build("session-1")

        self.assertEqual(result.messages[-1]["content"], "hello")
        self.assertIn("recall_ms", result.trace)
        self.assertEqual(result.trace["history_messages_loaded"], 1)
        self.assertEqual(result.trace["recent_messages_used"], 1)
        self.assertEqual(result.trace["todos_loaded"], 1)
        self.assertGreater(result.trace["total_context_tokens"], 0)
        self.assertIn("compaction_recommended", result.trace)
        self.assertEqual(result.trace["sources"]["history"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["summary"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["todos"]["status"], "ok")
        block_statuses = {
            block["name"]: block["status"]
            for block in result.trace["context_blocks"]["blocks"]
        }
        self.assertEqual(block_statuses["task_context"], "kept")
        self.assertEqual(block_statuses["session_summary"], "kept")
        self.assertIn("cache_versions", result.trace)
        self.assertIn("summary_version", result.trace["cache_versions"])
        self.assertIn("todo_version", result.trace["cache_versions"])
        self.assertIn("latest_message_version", result.trace["cache_versions"])

    def test_memory_trace_classifies_fast_and_slow_path(self):
        repository = FakeRepository()

        result = Memory(repository, history_limit=20).build("session-1")

        self.assertEqual(result.trace["recall_strategy"]["fast_path"], ["history", "todos"])
        self.assertEqual(result.trace["recall_strategy"]["slow_path"], ["summary"])
        self.assertEqual(result.trace["sources"]["history"]["path"], "fast")
        self.assertEqual(result.trace["sources"]["todos"]["path"], "fast")
        self.assertEqual(result.trace["sources"]["summary"]["path"], "slow")

    def test_simple_tool_intent_skips_slow_and_task_memory(self):
        repository = FakeRepository()

        result = Memory(repository, history_limit=20).build(
            "session-1", "计算 (1 + 2) * 3"
        )

        self.assertEqual(result.trace["recall_plan"]["intent"], "simple_tool")
        self.assertEqual(result.trace["sources"]["history"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["summary"]["status"], "skipped")
        self.assertEqual(result.trace["sources"]["todos"]["status"], "skipped")
        self.assertIn(("get_messages", "session-1", 20), repository.calls)
        self.assertNotIn(("get_session_summary", "session-1"), repository.calls)
        self.assertNotIn(("list_todos", "session-1"), repository.calls)

    def test_task_intent_recalls_task_memory_without_summary_by_default(self):
        repository = FakeRepository()

        result = Memory(repository, history_limit=20).build(
            "session-1", "刚才那个任务进度怎么样"
        )

        self.assertEqual(result.trace["recall_plan"]["intent"], "task_related")
        self.assertEqual(result.trace["sources"]["history"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["todos"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["summary"]["status"], "skipped")
        self.assertIn(("list_todos", "session-1"), repository.calls)

    def test_task_context_includes_current_step_for_active_task(self):
        repository = MultiTodoRepository()

        result = Memory(repository, history_limit=20).build(
            "session-1", "刚才那个任务继续做"
        )

        context = result.messages[1]["content"]
        self.assertIn('"current_step"', context)
        self.assertIn('"task_id": 2', context)
        self.assertIn("make product research PPT", context)
        self.assertIn('"phase": "working"', context)
        self.assertIn("Continue the current task", context)
        self.assertIn("Do not treat raw research", context)

    def test_task_context_does_not_invent_current_step_without_tasks(self):
        repository = EmptyTodoRepository()

        result = Memory(repository, history_limit=20).build(
            "session-1", "任务进度怎么样"
        )

        context = result.messages[1]["content"]
        self.assertIn('"current_step"', context)
        self.assertIn('"task_id": null', context)
        self.assertIn('"phase": "no_active_task"', context)
        self.assertIn("Do not invent a task state", context)

    def test_history_intent_recalls_summary_but_skips_task_memory(self):
        repository = FakeRepository()

        result = Memory(repository, history_limit=20).build(
            "session-1", "总结一下我们之前聊过什么"
        )

        self.assertEqual(result.trace["recall_plan"]["intent"], "history_related")
        self.assertEqual(result.trace["sources"]["history"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["summary"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["todos"]["status"], "skipped")
        self.assertIn(("get_session_summary", "session-1"), repository.calls)
        self.assertNotIn(("list_todos", "session-1"), repository.calls)

    def test_build_messages_trims_recent_conversation_by_token_budget(self):
        repository = FakeRepository()
        repository.get_messages = lambda session_id, limit: [
            {"role": "user", "content": "old " * 5000},
            {"role": "assistant", "content": "latest"},
        ]

        messages = Memory(repository, history_limit=20).build_messages("session-1")

        self.assertEqual(messages[-1]["content"], "latest")
        self.assertNotIn("old old old old", messages[-1]["content"])

    def test_build_uses_fallback_when_memory_source_times_out(self):
        repository = SlowSummaryRepository()
        started_at = time.perf_counter()

        result = Memory(repository, history_limit=20).build("session-1")

        elapsed = time.perf_counter() - started_at
        self.assertLess(elapsed, 0.5)
        self.assertIn("No compressed session summary yet.", result.messages[1]["content"])
        self.assertNotIn("late summary", result.messages[1]["content"])
        self.assertEqual(result.messages[-1]["content"], "hello")
        self.assertEqual(result.trace["sources"]["summary"]["status"], "timeout")
        self.assertTrue(result.trace["sources"]["summary"]["fallback_used"])
        self.assertEqual(result.trace["sources"]["history"]["status"], "ok")
        self.assertEqual(result.trace["sources"]["todos"]["status"], "ok")

    def test_slow_summary_uses_cached_summary_fallback(self):
        repository = FakeRepository()
        memory = Memory(repository, history_limit=20)

        first = memory.build("session-1")
        repository.get_session_summary = lambda session_id: (
            time.sleep(0.6) or "late summary"
        )
        second = memory.build("session-1")

        self.assertIn("summary text", first.messages[1]["content"])
        self.assertIn("summary text", second.messages[1]["content"])
        self.assertNotIn("late summary", second.messages[1]["content"])
        self.assertEqual(second.trace["sources"]["summary"]["status"], "timeout")
        self.assertTrue(second.trace["sources"]["summary"]["fallback_used"])
        self.assertTrue(second.trace["sources"]["summary"]["cache_fallback_available"])

    def test_context_priority_drops_lower_priority_blocks_when_budget_is_tight(self):
        repository = FakeRepository()
        original_budget = settings.agent_context_token_budget
        object.__setattr__(settings, "agent_context_token_budget", 20)
        try:
            result = Memory(repository, history_limit=20).build("session-1")
        finally:
            object.__setattr__(settings, "agent_context_token_budget", original_budget)

        self.assertIn("<TaskContext>", result.messages[1]["content"])
        block_statuses = {
            block["name"]: block["status"]
            for block in result.trace["context_blocks"]["blocks"]
        }
        self.assertTrue(block_statuses["task_context"].startswith("kept"))
        self.assertEqual(block_statuses["session_summary"], "dropped_budget")

    def test_context_cache_hits_for_same_summary_and_todos(self):
        repository = FakeRepository()
        memory = Memory(repository, history_limit=20)

        first = memory.build("session-1")
        second = memory.build("session-1")

        self.assertFalse(first.trace["context_blocks"]["cache_hit"])
        self.assertTrue(second.trace["context_blocks"]["cache_hit"])
        self.assertEqual(
            second.trace["context_blocks"]["cache_key_strategy"],
            "source_versions",
        )
        self.assertEqual(
            first.trace["cache_versions"],
            second.trace["context_blocks"]["versions"],
        )

    def test_context_cache_misses_when_task_state_changes(self):
        repository = FakeRepository()
        memory = Memory(repository, history_limit=20)

        first = memory.build("session-1")
        repository.list_todos = lambda session_id: [
            {"id": 1, "title": "demo changed", "status": "completed"}
        ]
        second = memory.build("session-1")

        self.assertFalse(first.trace["context_blocks"]["cache_hit"])
        self.assertFalse(second.trace["context_blocks"]["cache_hit"])
        self.assertNotEqual(
            first.trace["cache_versions"]["todo_version"],
            second.trace["cache_versions"]["todo_version"],
        )

    def test_context_cache_misses_when_latest_message_changes(self):
        repository = ChangingHistoryRepository()
        memory = Memory(repository, history_limit=20)

        first = memory.build("session-1")
        repository.message = "new user message"
        second = memory.build("session-1")

        self.assertFalse(first.trace["context_blocks"]["cache_hit"])
        self.assertFalse(second.trace["context_blocks"]["cache_hit"])
        self.assertNotEqual(
            first.trace["cache_versions"]["latest_message_version"],
            second.trace["cache_versions"]["latest_message_version"],
        )


if __name__ == "__main__":
    unittest.main()
