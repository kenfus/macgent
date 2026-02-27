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
    vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"
    browser_mode = "agent_browser"
    browser_fallback_threshold = 3
    captcha_auto_attempts = 1
    browser_reasoning_model = "arcee-ai/trinity-large-preview:free"
    browser_vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"
    browser_headed = False
    text_model_primary = "openrouter_primary"
    text_model_fallbacks = "openrouter_trinity,kilo_glm5"
    vision_model_primary = "openrouter_vision_primary"
    vision_model_fallbacks = "openrouter_nemotron_vl"
    model_config = {}
    kilo_browser_vision_model = ""
    kilo_api_key = ""
    kilo_api_base = "https://api.kilo.ai/v1"

    @staticmethod
    def get_error_policy():
        return {"retry_statuses": [429], "max_retries_per_offer": 1, "backoff_seconds": 0, "backoff_multiplier": 1}


def test_evaluate_image_action(monkeypatch):
    set_dispatch_config(DummyConfig())

    class FakeVisionClient:
        def chat_with_image(self, **kwargs):
            assert kwargs["prompt"] == "describe"
            return "image-description"

    monkeypatch.setattr("macgent.actions.dispatcher._build_dispatch_vision_client", lambda: FakeVisionClient())

    out = dispatch(Action(type="evaluate_image", params={"image_base64": "abcd", "prompt": "describe"}))
    assert out == "image-description"
