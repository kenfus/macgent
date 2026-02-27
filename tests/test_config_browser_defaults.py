from macgent.config import Config


def test_browser_defaults_present():
    cfg = Config.from_env()
    assert cfg.browser_mode in {"safari", "agent_browser", "hybrid"}
    assert cfg.browser_fallback_threshold >= 1
    assert cfg.captcha_auto_attempts >= 0
    assert cfg.browser_reasoning_model
    assert cfg.browser_vision_model
    assert cfg.brave_search_api_base
