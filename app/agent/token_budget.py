from typing import Any, Dict, Iterable, List


CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def estimate_message_tokens(message: Dict[str, Any]) -> int:
    total = 0
    for key in ("role", "name", "content", "tool_call_id"):
        value = message.get(key)
        if value:
            total += estimate_tokens(str(value))
    return total


def estimate_messages_tokens(messages: Iterable[Dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def trim_messages_to_budget(
    messages: List[Dict[str, Any]],
    max_tokens: int,
) -> List[Dict[str, Any]]:
    if max_tokens <= 0:
        return []

    selected: List[Dict[str, Any]] = []
    used_tokens = 0
    for message in reversed(messages):
        message_tokens = estimate_message_tokens(message)
        if selected and used_tokens + message_tokens > max_tokens:
            break
        if not selected and message_tokens > max_tokens:
            selected.append(_truncate_message(message, max_tokens))
            break
        selected.append(message)
        used_tokens += message_tokens
    selected.reverse()
    return selected


def _truncate_message(message: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    truncated = dict(message)
    content = str(truncated.get("content", ""))
    role_tokens = estimate_tokens(str(truncated.get("role", "")))
    content_budget = max(0, max_tokens - role_tokens)
    max_chars = content_budget * CHARS_PER_TOKEN
    if max_chars <= 0:
        truncated["content"] = ""
    elif len(content) > max_chars:
        truncated["content"] = content[-max_chars:]
    return truncated

