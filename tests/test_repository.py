import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.database import init_db
from app.repositories import Repository


class RepositoryTests(unittest.TestCase):
    def test_todo_persists_across_repository_instances(self):
        original_path = settings.database_path
        with tempfile.TemporaryDirectory() as directory:
            object.__setattr__(
                settings, "database_path", str(Path(directory) / "test.db")
            )
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


if __name__ == "__main__":
    unittest.main()
