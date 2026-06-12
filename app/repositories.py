import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def create_session(self, title: str) -> str:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title[:80], now, now),
            )
        return session_id

    def session_exists(self, session_id: str) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def touch_session(self, session_id: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (utc_now(), session_id),
            )

    def list_sessions(self) -> List[Dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, title, created_at, updated_at FROM sessions "
                "ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO messages(session_id, role, content, tool_call_id, name, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tool_call_id, name, utc_now()),
            )
        self.touch_session(session_id)

    def get_messages(self, session_id: str, limit: int) -> List[Dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT role, content, tool_call_id, name
                FROM (
                    SELECT id, role, content, tool_call_id, name
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_todo(self, session_id: str, title: str, details: str = "") -> Dict[str, Any]:
        now = utc_now()
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO todos(session_id, title, details, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, title, details, now, now),
            )
            todo_id = cursor.lastrowid
        return self.get_todo(session_id, todo_id)

    def get_todo(self, session_id: str, todo_id: int) -> Optional[Dict[str, Any]]:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id, title, status, details, created_at, updated_at "
                "FROM todos WHERE session_id = ? AND id = ?",
                (session_id, todo_id),
            ).fetchone()
        return dict(row) if row else None

    def list_todos(self, session_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (
            "SELECT id, title, status, details, created_at, updated_at "
            "FROM todos WHERE session_id = ?"
        )
        params: List[Any] = [session_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id DESC"
        with get_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def update_todo(
        self,
        session_id: str,
        todo_id: int,
        status: Optional[str] = None,
        details: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        todo = self.get_todo(session_id, todo_id)
        if not todo:
            return None
        next_status = status if status is not None else todo["status"]
        next_details = details if details is not None else todo["details"]
        with get_connection() as connection:
            connection.execute(
                "UPDATE todos SET status = ?, details = ?, updated_at = ? "
                "WHERE session_id = ? AND id = ?",
                (next_status, next_details, utc_now(), session_id, todo_id),
            )
        return self.get_todo(session_id, todo_id)

    def add_trace(
        self,
        request_id: str,
        session_id: str,
        step: int,
        event: str,
        name: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Any = None,
        error: Optional[str] = None,
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO traces(
                    request_id, session_id, step, event, name,
                    input_json, output_json, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    session_id,
                    step,
                    event,
                    name,
                    json.dumps(input_data, ensure_ascii=False) if input_data is not None else None,
                    json.dumps(output_data, ensure_ascii=False) if output_data is not None else None,
                    error,
                    utc_now(),
                ),
            )

    def get_traces(self, request_id: str) -> List[Dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT step, event, name, input_json, output_json, error, created_at
                FROM traces WHERE request_id = ? ORDER BY id
                """,
                (request_id,),
            ).fetchall()
        traces = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json")) if item["input_json"] else None
            item["output"] = json.loads(item.pop("output_json")) if item["output_json"] else None
            traces.append(item)
        return traces

