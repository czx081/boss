import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None



@unittest.skipIf(TestClient is None, "FastAPI is not installed in this Python environment")
class StreamApiTests(unittest.TestCase):
    def test_chat_stream_returns_sse_events(self):
        import app.main as main_module

        original_repository = main_module.repository
        original_runtime = main_module.runtime

        main_module.repository = FakeRepository()
        main_module.runtime = FakeRuntime()
        client = TestClient(main_module.app)

        try:
            with client.stream(
                "POST",
                "/api/chat/stream",
                json={"message": "hello"},
            ) as response:
                body = response.read().decode("utf-8")
        finally:
            main_module.repository = original_repository
            main_module.runtime = original_runtime

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: start", body)
        self.assertIn("event: trace", body)
        self.assertIn("event: answer", body)
        self.assertIn("event: done", body)


class FakeRepository:
    def session_exists(self, session_id):
        return session_id == "session-1"

    def create_session(self, title):
        return "session-1"

    def get_traces(self, request_id):
        return [
            {
                "step": 0,
                "event": "memory_recall",
                "name": None,
                "input": None,
                "output": {"recall_ms": 1},
                "error": None,
                "created_at": "2026-06-26T00:00:00",
            }
        ]


class FakeRuntime:
    def run(self, session_id, message):
        return "stream answer", "request-1"


if __name__ == "__main__":
    unittest.main()
