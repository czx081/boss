import unittest
from pathlib import Path
from uuid import uuid4

from app.agent.summary import SummaryCompactor
from app.config import settings
from app.database import init_db
from app.repositories import Repository


def use_test_database(name: str) -> str:
    path = Path("data") / "test-dbs" / "{}-{}.db".format(name, uuid4().hex)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


class SummaryCompactorTests(unittest.TestCase):
    def test_compact_now_updates_session_summary(self):
        original_path = settings.database_path
        object.__setattr__(
            settings, "database_path", use_test_database("summary-compactor")
        )
        try:
            init_db()
            repository = Repository()
            session_id = repository.create_session("summary")
            repository.add_message(session_id, "user", "我想做一个低延迟 Agent。")
            repository.add_message(session_id, "assistant", "可以先做 trace。")

            summary = SummaryCompactor(repository).compact_now(session_id)

            self.assertIn("低延迟 Agent", summary)
            self.assertIn("trace", summary)
            self.assertEqual(repository.get_session_summary(session_id), summary)
        finally:
            object.__setattr__(settings, "database_path", original_path)


if __name__ == "__main__":
    unittest.main()
