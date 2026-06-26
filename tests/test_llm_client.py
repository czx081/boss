import json
import unittest
from unittest.mock import patch

from app.agent.llm_client import LLMClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")


class LLMClientTests(unittest.TestCase):
    def test_chat_sends_max_tokens(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        client = LLMClient(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="test-model",
            max_tokens=123,
            timeout=7,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.chat(messages=[{"role": "user", "content": "hi"}], tools=[])

        self.assertEqual(response["content"], "ok")
        self.assertEqual(captured["payload"]["max_tokens"], 123)
        self.assertEqual(captured["payload"]["temperature"], 0.2)
        self.assertEqual(captured["timeout"], 7)


if __name__ == "__main__":
    unittest.main()
