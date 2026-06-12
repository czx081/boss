import json
from typing import Any, Dict, List

from app.agent.prompts import SYSTEM_PROMPT
from app.repositories import Repository


class Memory:
    def __init__(self, repository: Repository, history_limit: int):
        self.repository = repository
        self.history_limit = history_limit

    def build_messages(self, session_id: str) -> List[Dict[str, Any]]:
        history = self.repository.get_messages(session_id, self.history_limit)
        todos = self.repository.list_todos(session_id)
        state = {
            "session_id": session_id,
            "todos": todos,
        }
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Recalled session state:\n{}".format(
                    json.dumps(state, ensure_ascii=False)
                ),
            },
        ]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        return messages

