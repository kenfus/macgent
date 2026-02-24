import os
from dataclasses import dataclass, field
from pathlib import Path

# Default data directory
MACGENT_DIR = Path.home() / ".macgent"


@dataclass
class Config:
    # Reasoning model (text-only) — defaults to free OpenRouter models
    reasoning_api_base: str = "https://openrouter.ai/api/v1"
    reasoning_api_key: str = ""
    reasoning_model: str = "arcee-ai/trinity-large-preview:free"
    reasoning_api_type: str = "openai"

    # Vision model (optional)
    vision_api_base: str = "https://openrouter.ai/api/v1"
    vision_api_key: str = ""
    vision_model: str = "google/gemini-2.5-pro-exp-03-25:free"
    vision_api_type: str = "openai"

    # Agent settings
    max_steps: int = 30
    step_delay: float = 1.0
    screenshot_max_width: int = 1024
    page_text_max_chars: int = 4000
    use_vision: bool = False

    # Tools
    cliclick_path: str = "/opt/homebrew/bin/cliclick"

    # Per-role models (with fallback chains, comma-separated)
    manager_models: str = "google/gemma-3-27b-it:free,mistralai/mistral-small-3.1-24b-instruct:free,nvidia/nemotron-3-nano-30b-a3b:free"
    worker_models: str = "arcee-ai/trinity-large-preview:free,qwen/qwen3-coder:free,google/gemma-3-27b-it:free"

    # Daemon settings
    daemon_interval: int = 1800  # 30 minutes in seconds
    stale_task_minutes: int = 60

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Notion
    notion_token: str = ""
    notion_database_id: str = ""

    # Paths
    db_path: str = ""
    workspace_dir: str = ""    # agent runtime: role files + learned skills
    log_file: str = ""         # path to macgent.log
    faiss_path: str = ""
    memories_dir: str = ""     # daily memory .md files

    @classmethod
    def from_env(cls) -> "Config":
        macgent_dir = Path(os.getenv("MACGENT_DIR", str(MACGENT_DIR)))
        # Default workspace dir: use repo's workspace/ if it exists, else ~/.macgent/workspace
        _repo_workspace = Path(__file__).parent.parent / "workspace"
        default_workspace = str(_repo_workspace) if _repo_workspace.exists() else str(macgent_dir / "workspace")
        default_log = str(Path(default_workspace) / "macgent.log")
        return cls(
            reasoning_api_base=os.getenv("REASONING_API_BASE", cls.reasoning_api_base),
            reasoning_api_key=os.getenv("REASONING_API_KEY", ""),
            reasoning_model=os.getenv("REASONING_MODEL", cls.reasoning_model),
            reasoning_api_type=os.getenv("REASONING_API_TYPE", cls.reasoning_api_type),
            vision_api_base=os.getenv("VISION_API_BASE", cls.vision_api_base),
            vision_api_key=os.getenv("VISION_API_KEY", ""),
            vision_model=os.getenv("VISION_MODEL", cls.vision_model),
            vision_api_type=os.getenv("VISION_API_TYPE", cls.vision_api_type),
            max_steps=int(os.getenv("MAX_STEPS", str(cls.max_steps))),
            step_delay=float(os.getenv("STEP_DELAY", str(cls.step_delay))),
            use_vision=os.getenv("USE_VISION", "false").lower() == "true",
            manager_models=os.getenv("MANAGER_MODELS", cls.manager_models),
            worker_models=os.getenv("WORKER_MODELS", cls.worker_models),
            daemon_interval=int(os.getenv("DAEMON_INTERVAL", str(cls.daemon_interval))),
            stale_task_minutes=int(os.getenv("STALE_TASK_MINUTES", str(cls.stale_task_minutes))),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_database_id=os.getenv("NOTION_PLANNING_DATABASE_ID", ""),
            db_path=os.getenv("MACGENT_DB_PATH", str(macgent_dir / "macgent.db")),
            workspace_dir=os.getenv("MACGENT_WORKSPACE_DIR", default_workspace),
            log_file=os.getenv("MACGENT_LOG_FILE", default_log),
            faiss_path=os.getenv("MACGENT_FAISS_PATH", str(macgent_dir / "memory.faiss")),
            memories_dir=os.getenv("MACGENT_MEMORIES_DIR", str(macgent_dir / "memories")),
        )

    def get_model_chain(self, role: str) -> list[str]:
        """Get the fallback model chain for a role."""
        chains = {
            "manager": self.manager_models,
            "worker": self.worker_models,
        }
        return [m.strip() for m in chains.get(role, self.worker_models).split(",")]
