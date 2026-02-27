import httpx

from macgent.reasoning.llm_client import FallbackLLMClient, LLMOffer


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x.test/chat/completions")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"status {code}", request=req, response=resp)


def test_retry_429_then_success(monkeypatch):
    offers = [LLMOffer(alias="a", api_base="https://x.test", api_key="k", model="m")]
    client = FallbackLLMClient(
        offers,
        error_policy={
            "retry_statuses": [429],
            "max_retries_per_offer": 2,
            "backoff_seconds": 0,
            "backoff_multiplier": 1,
        },
    )

    calls = {"n": 0}

    def fake_chat(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(429)
        return "ok"

    monkeypatch.setattr(client.clients[0], "chat", fake_chat)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    out = client.chat([{"role": "user", "content": "hi"}])
    assert out == "ok"
    assert calls["n"] == 2
