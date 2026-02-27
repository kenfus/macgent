import json

from macgent.actions.dispatcher import dispatch, set_dispatch_config
from macgent.models import Action


class DummyConfig:
    notion_token = ""
    notion_database_id = ""
    workspace_dir = "workspace"
    reasoning_model = "arcee-ai/trinity-large-preview:free"
    reasoning_api_key = "k"
    reasoning_api_base = "https://openrouter.ai/api/v1"
    reasoning_api_type = "openai"
    vision_api_key = "k"
    vision_api_base = "https://openrouter.ai/api/v1"
    vision_api_type = "openai"
    browser_mode = "agent_browser"
    browser_fallback_threshold = 3
    captcha_auto_attempts = 1
    browser_reasoning_model = "arcee-ai/trinity-large-preview:free"
    browser_vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"
    vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"


def test_browser_task_dispatch(monkeypatch):
    set_dispatch_config(DummyConfig())

    def fake_run_browser_task(config, task_desc, mode=None, max_steps=None, capture_artifacts=True):
        payload = {
            "backend": "agent_browser",
            "attempts": 1,
            "solved": True,
            "blocked_reason": None,
            "task": task_desc,
            "mode": mode,
            "max_steps": max_steps,
            "capture_artifacts": capture_artifacts,
        }
        return json.dumps(payload)

    monkeypatch.setattr("macgent.actions.browser_use_action.run_browser_task", fake_run_browser_task)

    out = dispatch(
        Action(
            type="browser_task",
            params={"task": "Open https://example.com", "mode": "agent_browser", "max_steps": 12, "capture_artifacts": False},
        )
    )
    data = json.loads(out)
    assert data["backend"] == "agent_browser"
    assert data["solved"] is True
    assert data["max_steps"] == 12
    assert data["capture_artifacts"] is False
