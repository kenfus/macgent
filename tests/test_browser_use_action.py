import json
from types import SimpleNamespace

from macgent.actions import browser_use_action


def _cfg(tmp_path):
    return SimpleNamespace(
        workspace_dir=str(tmp_path / "workspace"),
        browser_mode="agent_browser",
        browser_headed=False,
        captcha_auto_attempts=1,
    )


def test_browser_task_blocks_without_url(monkeypatch, tmp_path):
    class FakeBrowser:
        def __init__(self, _cfg):
            self.opened = []

        def start(self):
            return self

        def close(self):
            return None

    monkeypatch.setattr(browser_use_action, "AgentBrowser", FakeBrowser)
    out = browser_use_action.run_browser_task(_cfg(tmp_path), "Search best hotels in Basel")
    data = json.loads(out)
    assert data["solved"] is False
    assert data["blocked_reason"] == "no_url_in_task_desc"


def test_browser_task_opens_explicit_url(monkeypatch, tmp_path):
    class FakeBrowser:
        def __init__(self, _cfg):
            self.opened = []

        def start(self):
            return self

        def open(self, url):
            self.opened.append(url)
            return "ok"

        def wait(self, _ms):
            return None

        def snapshot(self, interactive=True):
            return {"elements": []}

        def get_text(self):
            return "normal page"

        def get_title(self):
            return "Example"

        def get_url(self):
            return "https://example.com"

        def close(self):
            return None

    monkeypatch.setattr(browser_use_action, "AgentBrowser", FakeBrowser)
    out = browser_use_action.run_browser_task(_cfg(tmp_path), "Open https://example.com and summarize")
    data = json.loads(out)
    assert data["solved"] is True
    assert data["url"] == "https://example.com"
