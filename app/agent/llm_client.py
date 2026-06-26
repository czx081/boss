import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 800,
        timeout: float = 45.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise LLMError(
                "LLM_API_KEY is not configured. Copy .env.example to .env and set a real key."
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }
        try:
            request = urllib.request.Request(
                "{}/chat/completions".format(self.base_url),
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(
                "LLM API returned HTTP {}: {}".format(exc.code, detail)
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError("Could not connect to the LLM API: {}".format(exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMError("LLM request timed out") from exc

        try:
            data = json.loads(body)
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM API returned an invalid response") from exc
        return self._normalize_message(message)

    @staticmethod
    def _normalize_message(message: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        tool_calls: Optional[List[Dict[str, Any]]] = message.get("tool_calls")
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        return normalized
