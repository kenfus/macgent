import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default data directory
MACGENT_DIR = Path.home() / ".macgent"


@dataclass
class Config:
    # Agent identity (used only as fallback before identity.md exists)
    macgent_name: str = "MacGent"

    # Reasoning model (text-only) — defaults to free OpenRouter models
    reasoning_api_base: str = "https://openrouter.ai/api/v1"
    reasoning_api_key: str = ""
    reasoning_model: str = "arcee-ai/trinity-large-preview:free"
    reasoning_api_type: str = "openai"

    # Vision model (optional)
    vision_api_base: str = "https://openrouter.ai/api/v1"
    vision_api_key: str = ""
    vision_model: str = "nvidia/nemotron-nano-12b-v2-vl:free"
    vision_api_type: str = "openai"

    # Unified model routing aliases (can be overridden by macgent_config.json)
    text_model_primary: str = "openrouter_primary"
    text_model_fallbacks: str = "openrouter_trinity,kilo_glm5"
    vision_model_primary: str = "openrouter_vision_primary"
    vision_model_fallbacks: str = "openrouter_nemotron_vl"

    # Structured model config file
    model_config_path: str = ""
    model_config: dict[str, Any] = field(default_factory=dict)

    # Agent settings
    max_steps: int = 30
    step_delay: float = 1.0
    screenshot_max_width: int = 1024
    page_text_max_chars: int = 4000
    use_vision: bool = False

    # Browser backend strategy
    browser_mode: str = "agent_browser"
    browser_fallback_threshold: int = 3
    captcha_auto_attempts: int = 1
    browser_reasoning_model: str = "arcee-ai/trinity-large-preview:free"
    browser_vision_model: str = "nvidia/nemotron-nano-12b-v2-vl:free"
    browser_headed: bool = False

    # Optional last-resort provider
    kilo_api_base: str = "https://api.kilo.ai/v1"
    kilo_api_key: str = ""
    kilo_browser_vision_model: str = ""

    # External search providers
    brave_search_api_base: str = "https://api.search.brave.com"
    brave_search_api_key: str = ""

    # Tools
    cliclick_path: str = "/opt/homebrew/bin/cliclick"

    # Per-role legacy model chains
    manager_models: str = "google/gemma-3-27b-it:free,mistralai/mistral-small-3.1-24b-instruct:free,nvidia/nemotron-3-nano-30b-a3b:free"
    worker_models: str = "arcee-ai/trinity-large-preview:free,qwen/qwen3-coder:free,google/gemma-3-27b-it:free"

    # Daemon settings
    daemon_interval: int = 1800
    stale_task_minutes: int = 60

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Notion
    notion_token: str = ""
    notion_database_id: str = ""

    # Paths
    workspace_dir: str = ""
    log_file: str = ""
    faiss_path: str = ""
    memories_dir: str = ""

    # Memory context policy
    memory_recent_days: int = 2
    memory_top_k: int = 5

    @classmethod
    def _load_model_config(cls, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}

    @staticmethod
    def _split_csv(values: str) -> list[str]:
        return [v.strip() for v in (values or "").split(",") if v.strip()]

    @staticmethod
    def _route_value(cfg: dict[str, Any], section: str, key: str, default: Any) -> Any:
        return cfg.get("routes", {}).get(section, {}).get(key, default)

    @classmethod
    def from_env(cls) -> "Config":
        macgent_dir = Path(os.getenv("MACGENT_DIR", str(MACGENT_DIR)))
        repo_root = Path(__file__).parent.parent
        repo_workspace = repo_root / "workspace"
        default_workspace = str(repo_workspace)
        default_log = str(repo_root / "logs" / "macgent.log")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        reasoning_key = os.getenv("REASONING_API_KEY", openrouter_key)
        vision_key = os.getenv("VISION_API_KEY", openrouter_key or reasoning_key)

        default_cfg_path = str(Path.cwd() / "macgent_config.json")
        cfg_path = os.getenv("MACGENT_CONFIG_PATH", default_cfg_path)
        model_cfg = cls._load_model_config(cfg_path)
        runtime_cfg = model_cfg.get("runtime", {})
        integrations_cfg = model_cfg.get("integrations", {})
        workspace_from_cfg = str(runtime_cfg.get("workspace_dir", "")).strip()
        log_from_cfg = str(runtime_cfg.get("log_file", "")).strip()
        tg_token_env = str(integrations_cfg.get("telegram_bot_token_env", "TELEGRAM_BOT_TOKEN")).strip() or "TELEGRAM_BOT_TOKEN"
        tg_chat_env = str(integrations_cfg.get("telegram_chat_id_env", "TELEGRAM_CHAT_ID")).strip() or "TELEGRAM_CHAT_ID"
        tg_token_from_cfg = str(integrations_cfg.get("telegram_bot_token", "")).strip()
        tg_chat_from_cfg = str(integrations_cfg.get("telegram_chat_id", "")).strip()
        tg_token_from_env = os.getenv(tg_token_env, "").strip()
        tg_chat_from_env = os.getenv(tg_chat_env, "").strip()

        return cls(
            macgent_name=cls.macgent_name,
            reasoning_api_base=os.getenv("REASONING_API_BASE", cls.reasoning_api_base),
            reasoning_api_key=reasoning_key,
            reasoning_model=os.getenv("REASONING_MODEL", cls.reasoning_model),
            reasoning_api_type=os.getenv("REASONING_API_TYPE", cls.reasoning_api_type),
            vision_api_base=os.getenv("VISION_API_BASE", cls.vision_api_base),
            vision_api_key=vision_key,
            vision_model=os.getenv("VISION_MODEL", cls.vision_model),
            vision_api_type=os.getenv("VISION_API_TYPE", cls.vision_api_type),
            text_model_primary=os.getenv(
                "TEXT_MODEL_PRIMARY",
                cls._route_value(model_cfg, "text", "primary", cls.text_model_primary),
            ),
            text_model_fallbacks=os.getenv(
                "TEXT_MODEL_FALLBACKS",
                ",".join(cls._route_value(model_cfg, "text", "fallbacks", cls._split_csv(cls.text_model_fallbacks))),
            ),
            vision_model_primary=os.getenv(
                "VISION_MODEL_PRIMARY",
                cls._route_value(model_cfg, "vision", "primary", cls.vision_model_primary),
            ),
            vision_model_fallbacks=os.getenv(
                "VISION_MODEL_FALLBACKS",
                ",".join(cls._route_value(model_cfg, "vision", "fallbacks", cls._split_csv(cls.vision_model_fallbacks))),
            ),
            model_config_path=cfg_path,
            model_config=model_cfg,
            max_steps=int(os.getenv("MAX_STEPS", str(cls.max_steps))),
            step_delay=float(os.getenv("STEP_DELAY", str(cls.step_delay))),
            use_vision=os.getenv("USE_VISION", "false").lower() == "true",
            browser_mode=os.getenv("BROWSER_MODE", "agent_browser"),
            browser_fallback_threshold=int(os.getenv("BROWSER_FALLBACK_THRESHOLD", "3")),
            captcha_auto_attempts=int(os.getenv("CAPTCHA_AUTO_ATTEMPTS", "1")),
            browser_reasoning_model=os.getenv("BROWSER_REASONING_MODEL", cls.browser_reasoning_model),
            browser_vision_model=os.getenv("BROWSER_VISION_MODEL", cls.browser_vision_model),
            browser_headed=os.getenv("BROWSER_HEADED", "false").lower() == "true",
            kilo_api_base=os.getenv("KILO_API_BASE", cls.kilo_api_base),
            kilo_api_key=os.getenv("KILO_API_KEY", ""),
            kilo_browser_vision_model=os.getenv("KILO_BROWSER_VISION_MODEL", ""),
            brave_search_api_base=os.getenv("BRAVE_SEARCH_API_BASE", cls.brave_search_api_base),
            brave_search_api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
            manager_models=os.getenv("MANAGER_MODELS", cls.manager_models),
            worker_models=os.getenv("WORKER_MODELS", cls.worker_models),
            daemon_interval=int(os.getenv("DAEMON_INTERVAL", str(cls.daemon_interval))),
            stale_task_minutes=int(os.getenv("STALE_TASK_MINUTES", str(cls.stale_task_minutes))),
            telegram_bot_token=tg_token_from_env or tg_token_from_cfg,
            telegram_chat_id=tg_chat_from_env or tg_chat_from_cfg,
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_database_id=os.getenv("NOTION_PLANNING_DATABASE_ID", ""),
            workspace_dir=workspace_from_cfg or default_workspace,
            log_file=log_from_cfg or default_log,
            faiss_path=os.getenv("MACGENT_FAISS_PATH", str(macgent_dir / "memory.faiss")),
            memories_dir=os.getenv("MACGENT_MEMORIES_DIR", str(macgent_dir / "memories")),
            memory_recent_days=int(os.getenv("MEMORY_RECENT_DAYS", str(cls.memory_recent_days))),
            memory_top_k=int(os.getenv("MEMORY_TOP_K", str(cls.memory_top_k))),
        )

    def get_model_chain(self, role: str) -> list[str]:
        chains = {
            "manager": self.manager_models,
            "worker": self.worker_models,
        }
        return [m.strip() for m in chains.get(role, self.worker_models).split(",") if m.strip()]

    def get_text_offer_chain(self) -> list[str]:
        route = self.model_config.get("routes", {}).get("text", {})
        primary = route.get("primary", self.text_model_primary)
        fallbacks = route.get("fallbacks", self._split_csv(self.text_model_fallbacks))
        return [primary, *fallbacks]

    def get_vision_offer_chain(self) -> list[str]:
        route = self.model_config.get("routes", {}).get("vision", {})
        primary = route.get("primary", self.vision_model_primary)
        fallbacks = route.get("fallbacks", self._split_csv(self.vision_model_fallbacks))
        return [primary, *fallbacks]

    def get_browser_text_offer_chain(self) -> list[str]:
        route = self.model_config.get("routes", {}).get("browser", {}).get("text", {})
        primary = route.get("primary", self.browser_reasoning_model or self.text_model_primary)
        fallbacks = route.get("fallbacks", self._split_csv(self.text_model_fallbacks))
        return [primary, *fallbacks]

    def get_browser_vision_offer_chain(self) -> list[str]:
        route = self.model_config.get("routes", {}).get("browser", {}).get("vision", {})
        primary = route.get("primary", self.browser_vision_model or self.vision_model_primary)
        fallbacks = route.get("fallbacks", self._split_csv(self.vision_model_fallbacks))
        if self.kilo_browser_vision_model:
            fallbacks = [*fallbacks, self.kilo_browser_vision_model]
        return [primary, *fallbacks]

    def get_error_policy(self) -> dict[str, Any]:
        policy = self.model_config.get("error_policy", {})
        return {
            "retry_statuses": policy.get("retry_statuses", [429, 503, 504]),
            "max_retries_per_offer": int(policy.get("max_retries_per_offer", 2)),
            "backoff_seconds": float(policy.get("backoff_seconds", 1.5)),
            "backoff_multiplier": float(policy.get("backoff_multiplier", 2.0)),
        }

    def get_provider_definition(self, provider: str) -> dict[str, Any] | None:
        return self.model_config.get("providers", {}).get(provider)

    def get_offer_definition(self, alias: str, modality: str) -> dict[str, Any] | None:
        return self.model_config.get("offers", {}).get(modality, {}).get(alias)

    def get_logging_level(self) -> str:
        level = os.getenv("MACGENT_LOG_LEVEL", self.model_config.get("logging", {}).get("level", "INFO"))
        level = str(level or "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return "INFO"
        return level
