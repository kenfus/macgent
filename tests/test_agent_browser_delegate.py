import json

from macgent.agent import Agent
from macgent.config import Config


class DummyCfg(Config):
    def __init__(self):
        super().__init__()
        self.reasoning_api_key = "test"
        self.browser_mode = "agent_browser"
        self.workspace_dir = "workspace"


def test_delegate_sets_completed_when_solved(monkeypatch):
    cfg = DummyCfg()
    agent = Agent(cfg)

    def fake_dispatch(action):
        return json.dumps({"backend": "agent_browser", "solved": True, "blocked_reason": None})

    monkeypatch.setattr("macgent.agent.dispatch", fake_dispatch)

    state = agent.run("Open https://example.com and summarize")
    assert state.status == "completed"
    assert state.steps


def test_delegate_keeps_macos_tasks_on_loop():
    cfg = DummyCfg()
    agent = Agent(cfg)
    assert agent._is_macos_direct_task("Read my inbox") is True
    assert agent._is_macos_direct_task("Open booking.com") is False
