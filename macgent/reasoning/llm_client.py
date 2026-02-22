import httpx
import json
import logging
from typing import Optional

logger = logging.getLogger("macgent.llm")


class LLMClient:
    """Minimal LLM client supporting OpenAI and Anthropic APIs."""

    def __init__(self, api_base: str, api_key: str, model: str, api_type: str = "openai"):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_type = api_type
        self.http = httpx.Client(timeout=180.0)  # Reasoning models can be slow

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        if self.api_type == "anthropic":
            return self._call_anthropic(messages, system, max_tokens, temperature)
        else:
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
        else:
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
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.debug(f"POST {url} model={self.model}")
        resp = self.http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
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

        logger.debug(f"POST {url} model={self.model}")
        resp = self.http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
