from typing import Optional

from app.repositories import Repository


VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class TodoTool:
    def __init__(self, repository: Repository):
        self.repository = repository

    def execute(
        self,
        session_id: str,
        action: str,
        title: Optional[str] = None,
        todo_id: Optional[int] = None,
        status: Optional[str] = None,
        details: Optional[str] = None,
    ) -> dict:
        if action == "create":
            if not title:
                raise ValueError("title is required for create")
            return {"todo": self.repository.create_todo(session_id, title, details or "")}
        if action == "list":
            if status and status not in VALID_STATUSES:
                raise ValueError("Invalid status")
            return {"todos": self.repository.list_todos(session_id, status)}
        if action == "get":
            if todo_id is None:
                raise ValueError("todo_id is required for get")
            todo = self.repository.get_todo(session_id, todo_id)
            if not todo:
                raise ValueError("Todo not found")
            return {"todo": todo}
        if action == "update":
            if todo_id is None:
                raise ValueError("todo_id is required for update")
            if status and status not in VALID_STATUSES:
                raise ValueError("Invalid status")
            todo = self.repository.update_todo(session_id, todo_id, status, details)
            if not todo:
                raise ValueError("Todo not found")
            return {"todo": todo}
        raise ValueError("action must be create, list, get, or update")

