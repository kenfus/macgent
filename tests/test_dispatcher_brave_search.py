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
    vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"
    brave_search_api_key = "brave-k"
    brave_search_api_base = "https://api.search.brave.com"


def test_dispatcher_brave_search(monkeypatch):
    set_dispatch_config(DummyConfig())

    def fake_brave(**kwargs):
        assert kwargs["api_key"] == "brave-k"
        assert kwargs["query"] == "macos accessibility"
        return json.dumps({"query": kwargs["query"], "count": 1, "results": []})

    monkeypatch.setattr("macgent.actions.dispatcher.brave_web_search_json", fake_brave)

    out = dispatch(Action(type="brave_search", params={"query": "macos accessibility", "count": 3}))
    data = json.loads(out)
    assert data["query"] == "macos accessibility"


def test_dispatcher_brave_search_requires_query():
    set_dispatch_config(DummyConfig())
    out = dispatch(Action(type="brave_search", params={}))
    assert "needs 'query'" in out
