import os
from dataclasses import dataclass


@dataclass
class Config:
    # Reasoning model (text-only, cheap)
    reasoning_api_base: str = "https://api.anthropic.com"
    reasoning_api_key: str = ""
    reasoning_model: str = "claude-haiku-4-5-20251001"
    reasoning_api_type: str = "anthropic"  # anthropic | openai

    # Vision model (cheap, accepts images)
    vision_api_base: str = "https://api.openai.com/v1"
    vision_api_key: str = ""
    vision_model: str = "gpt-4o-mini"
    vision_api_type: str = "openai"  # openai | anthropic

    # Agent settings
    max_steps: int = 30
    step_delay: float = 1.0
    screenshot_max_width: int = 1024
    page_text_max_chars: int = 4000
    use_vision: bool = True

    # Tools
    cliclick_path: str = "/opt/homebrew/bin/cliclick"

    @classmethod
    def from_env(cls) -> "Config":
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
            use_vision=os.getenv("USE_VISION", "true").lower() == "true",
        )
