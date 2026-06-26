from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from app.repositories import Repository


class SummaryCompactor:
    def __init__(
        self,
        repository: Repository,
        history_limit: int = 20,
        max_summary_chars: int = 1200,
    ):
        self.repository = repository
        self.history_limit = history_limit
        self.max_summary_chars = max_summary_chars
        self._executor = ThreadPoolExecutor(max_workers=1)

    def schedule_if_needed(self, session_id: str, memory_trace: Dict) -> bool:
        if not memory_trace.get("compaction_recommended"):
            return False
        self._executor.submit(self.compact_now, session_id)
        return True

    def compact_now(self, session_id: str) -> str:
        messages = self.repository.get_messages(session_id, self.history_limit)
        summary = self._summarize_messages(messages)
        self.repository.update_session_summary(session_id, summary)
        return summary

    def _summarize_messages(self, messages: List[Dict]) -> str:
        if not messages:
            return ""
        lines = []
        for message in messages:
            role = message.get("role", "unknown")
            content = " ".join(str(message.get("content", "")).split())
            if not content:
                continue
            lines.append("{}: {}".format(role, content))
        summary = "\n".join(lines)
        if len(summary) <= self.max_summary_chars:
            return summary
        return summary[-self.max_summary_chars:]
