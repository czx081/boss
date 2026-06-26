import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file()


@dataclass(frozen=True)
class Settings:
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "800"))
    agent_max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "6"))
    agent_history_limit: int = int(os.getenv("AGENT_HISTORY_LIMIT", "20"))
    agent_context_token_budget: int = int(
        os.getenv("AGENT_CONTEXT_TOKEN_BUDGET", "12000")
    )
    agent_summary_trigger_ratio: float = float(
        os.getenv("AGENT_SUMMARY_TRIGGER_RATIO", "0.5")
    )
    agent_recent_token_budget: int = int(
        os.getenv("AGENT_RECENT_TOKEN_BUDGET", "5000")
    )
    agent_task_context_token_budget: int = int(
        os.getenv("AGENT_TASK_CONTEXT_TOKEN_BUDGET", "1500")
    )
    agent_memory_recall_timeout_ms: int = int(
        os.getenv("AGENT_MEMORY_RECALL_TIMEOUT_MS", "200")
    )
    database_path: str = os.getenv("DATABASE_PATH", "data/agent.db")


settings = Settings()
