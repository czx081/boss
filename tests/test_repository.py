import unittest
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.database import init_db
from app.repositories import Repository


def use_test_database(name: str) -> str:
    path = Path("data") / "test-dbs" / "{}-{}.db".format(name, uuid4().hex)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


class RepositoryTests(unittest.TestCase):
    def test_todo_persists_across_repository_instances(self):
        original_path = settings.database_path
        object.__setattr__(settings, "database_path", use_test_database("todo"))
        try:
            init_db()
            first = Repository()
            session_id = first.create_session("test")
            created = first.create_todo(session_id, "prepare demo")

            second = Repository()
            todos = second.list_todos(session_id)
            self.assertEqual(todos[0]["id"], created["id"])
            self.assertEqual(todos[0]["status"], "pending")

            updated = second.update_todo(
                session_id, created["id"], status="in_progress"
            )
            self.assertEqual(updated["status"], "in_progress")
        finally:
            object.__setattr__(settings, "database_path", original_path)

    def test_session_summary_can_be_read_and_updated(self):
        original_path = settings.database_path
        object.__setattr__(settings, "database_path", use_test_database("summary"))
        try:
            init_db()
            repository = Repository()
            session_id = repository.create_session("summary")

            self.assertEqual(repository.get_session_summary(session_id), "")

            repository.update_session_summary(
                session_id, "用户想做一个 Agent 框架优化方案。"
            )

            self.assertEqual(
                repository.get_session_summary(session_id),
                "用户想做一个 Agent 框架优化方案。",
            )
        finally:
            object.__setattr__(settings, "database_path", original_path)


if __name__ == "__main__":
    unittest.main()
