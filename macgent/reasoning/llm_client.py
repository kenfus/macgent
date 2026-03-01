import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Callable

import httpx

logger = logging.getLogger("macgent.llm")


class ProviderError(RuntimeError):
    """Provider returned 200 OK but with no valid response body (e.g. no choices).
    Treated as retryable — the model may be briefly overloaded."""


class LLMClient:
    """Minimal LLM client supporting OpenAI and Anthropic APIs."""

    def __init__(self, api_base: str, api_key: str, model: str, api_type: str = "openai"):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_type = api_type
        self.http = httpx.Client(timeout=180.0)

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        if self.api_type == "anthropic":
            return self._call_anthropic(messages, system, max_tokens, temperature)
        return self._call_openai(messages, system, max_tokens, temperature)

    def chat_with_image(
        self,
        prompt: str,
        image_base64: str,
        image_media_type: str = "image/png",
        system: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        if self.api_type == "anthropic":
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": image_media_type, "data": image_base64}},
                    {"type": "text", "text": prompt},
                ],
            }]
            return self._call_anthropic(messages, system, max_tokens, 0.0)

        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{image_base64}"}},
                {"type": "text", "text": prompt},
            ],
        }]
        return self._call_openai(messages, system, max_tokens, 0.0)

    def _call_openai(self, messages: list, system: Optional[str], max_tokens: int, temperature: float) -> str:
        url = f"{self.api_base}/chat/completions"
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.debug("POST %s model=%s", url, self.model)
        resp = self.http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if "choices" not in data:
            err = data.get("error", data)
            raise ProviderError(f"No choices in response from {self.model}: {err}")
        return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, messages: list, system: Optional[str], max_tokens: int, temperature: float) -> str:
        url = f"{self.api_base}/v1/messages"
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        logger.debug("POST %s model=%s", url, self.model)
        resp = self.http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


@dataclass
class LLMOffer:
    alias: str
    api_base: str
    api_key: str
    model: str
    api_type: str = "openai"


def _default_offer_catalog(config) -> dict[str, LLMOffer]:
    kilo_base = config.kilo_api_base or "https://api.kilo.ai/v1"
    return {
        "openrouter_primary": LLMOffer(
            alias="openrouter_primary",
            api_base=config.reasoning_api_base,
            api_key=config.reasoning_api_key,
            model=config.reasoning_model,
            api_type=config.reasoning_api_type,
        ),
        "openrouter_vision_primary": LLMOffer(
            alias="openrouter_vision_primary",
            api_base=config.vision_api_base,
            api_key=config.vision_api_key or config.reasoning_api_key,
            model=config.vision_model,
            api_type=config.vision_api_type,
        ),
        "openrouter_trinity": LLMOffer(
            alias="openrouter_trinity",
            api_base=config.reasoning_api_base,
            api_key=config.reasoning_api_key,
            model="arcee-ai/trinity-large-preview:free",
            api_type=config.reasoning_api_type,
        ),
        "openrouter_nemotron_text": LLMOffer(
            alias="openrouter_nemotron_text",
            api_base=config.reasoning_api_base,
            api_key=config.reasoning_api_key,
            model="nvidia/nemotron-3-nano-30b-a3b:free",
            api_type=config.reasoning_api_type,
        ),
        "openrouter_nemotron_vl": LLMOffer(
            alias="openrouter_nemotron_vl",
            api_base=config.vision_api_base,
            api_key=config.vision_api_key or config.reasoning_api_key,
            model="nvidia/nemotron-nano-12b-v2-vl:free",
            api_type=config.vision_api_type,
        ),
        "kilo_glm5": LLMOffer(
            alias="kilo_glm5",
            api_base=kilo_base,
            api_key=config.kilo_api_key,
            model="z-ai/glm-5:free",
            api_type="openai",
        ),
        "kilo_glm47": LLMOffer(
            alias="kilo_glm47",
            api_base=kilo_base,
            api_key=config.kilo_api_key,
            model="z-ai/glm-4.7:free",
            api_type="openai",
        ),
    }


def _offer_from_json_config(config, alias: str, modality: str) -> LLMOffer | None:
    offer_def = config.get_offer_definition(alias, modality) if hasattr(config, "get_offer_definition") else None
    if not offer_def:
        return None

    provider_name = offer_def.get("provider", "")
    provider = config.get_provider_definition(provider_name) if hasattr(config, "get_provider_definition") else None
    if not provider:
        return None

    api_key = ""
    key_env = provider.get("api_key_env", "")
    if key_env:
        api_key = os.getenv(key_env, "")
    if not api_key:
        api_key = provider.get("api_key", "")

    return LLMOffer(
        alias=alias,
        api_base=provider.get("api_base", ""),
        api_key=api_key,
        model=offer_def.get("model", ""),
        api_type=provider.get("api_type", "openai"),
    )


def resolve_offers(config, aliases: list[str], modality: str = "text") -> list[LLMOffer]:
    catalog = _default_offer_catalog(config)
    resolved: list[LLMOffer] = []

    for alias in aliases:
        offer = _offer_from_json_config(config, alias, modality)
        if offer is None:
            if alias in catalog:
                offer = catalog[alias]
            else:
                if modality == "vision":
                    offer = LLMOffer(
                        alias=alias,
                        api_base=config.vision_api_base,
                        api_key=config.vision_api_key or config.reasoning_api_key,
                        model=alias,
                        api_type=config.vision_api_type,
                    )
                else:
                    offer = LLMOffer(
                        alias=alias,
                        api_base=config.reasoning_api_base,
                        api_key=config.reasoning_api_key,
                        model=alias,
                        api_type=config.reasoning_api_type,
                    )

        if not offer.api_key:
            logger.warning("Skipping offer %s: missing API key", offer.alias)
            continue
        if not offer.api_base or not offer.model:
            logger.warning("Skipping offer %s: incomplete provider/model config", offer.alias)
            continue
        resolved.append(offer)

    return resolved


class FallbackLLMClient:
    """Tries multiple providers/models in order with centralized retry/backoff policy."""

    def __init__(self, offers: list[LLMOffer], error_policy: dict | None = None):
        self.offers = offers
        self.clients = [LLMClient(o.api_base, o.api_key, o.model, o.api_type) for o in offers]
        if not self.clients:
            raise RuntimeError("No valid LLM offers configured (check macgent_config.json or API keys).")

        policy = error_policy or {}
        self.retry_statuses = set(int(x) for x in policy.get("retry_statuses", [429, 503, 504]))
        self.max_retries_per_offer = int(policy.get("max_retries_per_offer", 2))
        self.backoff_seconds = float(policy.get("backoff_seconds", 1.5))
        self.backoff_multiplier = float(policy.get("backoff_multiplier", 2.0))

    @staticmethod
    def _error_status(exc: Exception) -> int | None:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            return exc.response.status_code
        return None

    def _run_with_retries(self, offer: LLMOffer, fn: Callable[[], str], modality: str) -> str:
        delay = self.backoff_seconds
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries_per_offer + 2):
            try:
                logger.info("%s_try alias=%s model=%s attempt=%s", modality, offer.alias, offer.model, attempt)
                return fn()
            except Exception as e:
                last_error = e
                status = self._error_status(e)
                is_retryable = status in self.retry_statuses or isinstance(e, ProviderError)
                logger.warning(
                    "%s_fail alias=%s model=%s status=%s attempt=%s error=%s",
                    modality,
                    offer.alias,
                    offer.model,
                    status,
                    attempt,
                    e,
                )
                if is_retryable and attempt <= self.max_retries_per_offer:
                    logger.info("%s_retry_wait alias=%s seconds=%.2f", modality, offer.alias, delay)
                    time.sleep(delay)
                    delay *= self.backoff_multiplier
                    continue
                break

        raise RuntimeError(f"Offer {offer.alias} failed after retries: {last_error}")

    def _debug_log_text_io(
        self,
        offer: LLMOffer,
        messages: list[dict],
        system: Optional[str],
        response: Optional[str] = None,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        if response is None:
            lines: list[str] = [
                "LLM_PROMPT_BEGIN",
                f"alias: {offer.alias}",
                f"model: {offer.model}",
                "",
                "━━━ CONTEXT (system) ━━━",
                "",
                (system or "(empty)"),
            ]
            # First message = task prompt (bootstrap / heartbeat / CEO message)
            if messages:
                first = messages[0]
                content = first.get("content", "")
                rendered = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
                lines.extend(["", "━━━ TASK ━━━", "", rendered])
            # Remaining messages = multi-turn conversation (action results injected by orchestrator)
            for idx, msg in enumerate(messages[1:], 1):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                rendered = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
                lines.extend(["", f"━━━ TURN {idx} ({role}) ━━━", "", rendered])
            lines.extend(["", "LLM_PROMPT_END"])
            logger.debug("\n".join(lines))
        else:
            logger.debug(
                "LLM_RESPONSE_BEGIN\nalias: %s\nmodel: %s\n\n%s\n\nLLM_RESPONSE_END",
                offer.alias,
                offer.model,
                response or "",
            )

    def _debug_log_vision_io(
        self,
        offer: LLMOffer,
        prompt: str,
        image_base64: str,
        response: Optional[str] = None,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        if response is None:
            logger.debug(
                "VISION_PROMPT_BEGIN\nalias=%s\nmodel=%s\nprompt:\n%s\nimage_bytes_b64=%s\nVISION_PROMPT_END",
                offer.alias,
                offer.model,
                prompt,
                len(image_base64),
            )
        else:
            logger.debug(
                "VISION_RESPONSE_BEGIN\nalias=%s\nmodel=%s\ncontent:\n%s\nVISION_RESPONSE_END",
                offer.alias,
                offer.model,
                response,
            )

    def chat(self, messages: list[dict], system: Optional[str] = None,
             max_tokens: int = 2048, temperature: float = 0.0) -> str:
        last_error = None
        for offer, client in zip(self.offers, self.clients):
            try:
                self._debug_log_text_io(offer, messages, system)
                result = self._run_with_retries(
                    offer,
                    lambda: client.chat(messages, system=system, max_tokens=max_tokens, temperature=temperature),
                    "llm",
                )
                self._debug_log_text_io(offer, messages, system, response=result)
                return result
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All text offers failed. Last error: {last_error}")

    def chat_with_image(
        self,
        prompt: str,
        image_base64: str,
        image_media_type: str = "image/png",
        system: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        last_error = None
        for offer, client in zip(self.offers, self.clients):
            try:
                self._debug_log_vision_io(offer, prompt, image_base64)
                result = self._run_with_retries(
                    offer,
                    lambda: client.chat_with_image(
                        prompt=prompt,
                        image_base64=image_base64,
                        image_media_type=image_media_type,
                        system=system,
                        max_tokens=max_tokens,
                    ),
                    "vision",
                )
                self._debug_log_vision_io(offer, prompt, image_base64, response=result)
                return result
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All vision offers failed. Last error: {last_error}")


def build_text_fallback_client(config) -> FallbackLLMClient:
    offers = resolve_offers(config, config.get_text_offer_chain(), modality="text")
    return FallbackLLMClient(offers, error_policy=config.get_error_policy())


def build_vision_fallback_client(config) -> FallbackLLMClient:
    offers = resolve_offers(config, config.get_vision_offer_chain(), modality="vision")
    return FallbackLLMClient(offers, error_policy=config.get_error_policy())
