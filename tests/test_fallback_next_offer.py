import httpx

from macgent.reasoning.llm_client import FallbackLLMClient, LLMOffer


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x.test/chat/completions")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"status {code}", request=req, response=resp)


def test_falls_back_to_next_offer(monkeypatch):
    offers = [
        LLMOffer(alias="a", api_base="https://a.test", api_key="k", model="m1"),
        LLMOffer(alias="b", api_base="https://b.test", api_key="k", model="m2"),
    ]
    client = FallbackLLMClient(
        offers,
        error_policy={
            "retry_statuses": [429],
            "max_retries_per_offer": 0,
            "backoff_seconds": 0,
            "backoff_multiplier": 1,
        },
    )

    monkeypatch.setattr(client.clients[0], "chat", lambda *a, **k: (_ for _ in ()).throw(_status_error(429)))
    monkeypatch.setattr(client.clients[1], "chat", lambda *a, **k: "ok-from-second")

    out = client.chat([{"role": "user", "content": "hi"}])
    assert out == "ok-from-second"
