from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.repositories import Repository
from app.tools.calculator import calculate
from app.tools.search import search
from app.tools.todo import TodoTool
from app.tools.weather import get_weather


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Dict[str, Any]]
    needs_session: bool = False
    readonly: bool = True
    can_parallel: bool = True
    risk_level: str = "low"

    def as_llm_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, repository: Repository):
        todo_tool = TodoTool(repository)
        self._schema_cache: Optional[List[Dict[str, Any]]] = None
        self._tools = {
            "calculator": Tool(
                "calculator",
                "Safely evaluate a numeric arithmetic expression.",
                {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                    },
                    "required": ["expression"],
                    "additionalProperties": False,
                },
                calculate,
                readonly=True,
                can_parallel=True,
                risk_level="low",
            ),
            "search": Tool(
                "search",
                "Search a small local knowledge base. This is a mock search tool.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                search,
                readonly=True,
                can_parallel=True,
                risk_level="low",
            ),
            "weather": Tool(
                "weather",
                "Get deterministic mock weather for a city.",
                {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
                get_weather,
                readonly=True,
                can_parallel=True,
                risk_level="low",
            ),
            "todo": Tool(
                "todo",
                "Create, list, get, or update durable todos for the current session.",
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "list", "get", "update"],
                        },
                        "title": {"type": "string"},
                        "todo_id": {"type": "integer"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                        },
                        "details": {"type": "string"},
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                todo_tool.execute,
                needs_session=True,
                readonly=False,
                can_parallel=False,
                risk_level="medium",
            ),
        }

    def schemas(self) -> List[Dict[str, Any]]:
        if self._schema_cache is None:
            self._schema_cache = [tool.as_llm_schema() for tool in self._tools.values()]
        return self._schema_cache

    def can_execute_parallel(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.readonly and tool.can_parallel)

    def execute(self, name: str, arguments: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError("Unknown tool: {}".format(name))
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if tool.needs_session:
            return tool.handler(session_id=session_id, **arguments)
        return tool.handler(**arguments)
