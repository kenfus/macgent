import pytest

from macgent.actions.brave_search import brave_web_search


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_brave_web_search_normalizes_payload(monkeypatch):
    payload = {
        "web": {
            "results": [
                {"title": "A", "url": "https://a.test", "description": "desc-a", "age": "2d"},
                {"title": "B", "url": "https://b.test", "description": "desc-b"},
            ]
        }
    }

    def fake_get(self, url, headers, params):
        assert url == "https://api.search.brave.com/res/v1/web/search"
        assert headers["X-Subscription-Token"] == "k"
        assert params["q"] == "basel hotels"
        assert params["count"] == 5
        return _FakeResponse(payload)

    monkeypatch.setattr("httpx.Client.get", fake_get)

    out = brave_web_search(api_key="k", query="basel hotels", count=5)
    assert out["query"] == "basel hotels"
    assert out["count"] == 2
    assert out["results"][0]["title"] == "A"
    assert out["results"][1]["url"] == "https://b.test"


def test_brave_web_search_requires_api_key():
    with pytest.raises(RuntimeError):
        brave_web_search(api_key="", query="x")
