from types import SimpleNamespace

from macgent.reasoning.llm_client import resolve_offers


def _cfg():
    return SimpleNamespace(
        reasoning_api_base="https://openrouter.ai/api/v1",
        reasoning_api_key="rk",
        reasoning_model="arcee-ai/trinity-large-preview:free",
        reasoning_api_type="openai",
        vision_api_base="https://openrouter.ai/api/v1",
        vision_api_key="vk",
        vision_model="nvidia/nemotron-nano-12b-v2-vl:free",
        vision_api_type="openai",
        kilo_api_base="https://api.kilo.ai/v1",
        kilo_api_key="kk",
    )


def test_resolve_aliases_text():
    offers = resolve_offers(_cfg(), ["openrouter_primary", "kilo_glm5"], modality="text")
    assert [o.alias for o in offers] == ["openrouter_primary", "kilo_glm5"]


def test_resolve_unknown_as_direct_model():
    offers = resolve_offers(_cfg(), ["qwen/qwen3-coder:free"], modality="text")
    assert len(offers) == 1
    assert offers[0].model == "qwen/qwen3-coder:free"
