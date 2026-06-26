import unittest

from app.repositories import Repository
from app.tools.registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_schemas_are_cached(self):
        registry = ToolRegistry(Repository())

        first = registry.schemas()
        second = registry.schemas()

        self.assertIs(first, second)
        self.assertTrue(first)


if __name__ == "__main__":
    unittest.main()
