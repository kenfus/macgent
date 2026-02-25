#!/usr/bin/env python3
"""
Kilo Gateway Client - Direct HTTP client for Kilo's OpenAI-compatible gateway API.

This module provides a minimal client for interacting with Kilo's gateway API
without requiring the Kilo CLI. It supports:
- Chat completions (OpenAI-compatible)
- Vision/image inputs via base64
- Streaming responses

Usage:
    from gateway_client import KiloGatewayClient

    client = KiloGatewayClient()  # Uses KILO_API_KEY env var

    # Basic chat
    response = client.chat([{"role": "user", "content": "Hello!"}])

    # With image
    response = client.chat_with_image("Describe this", image_base64="...")

    # Streaming
    for chunk in client.stream_chat([{"role": "user", "content": "Tell me a story"}]):
        print(chunk, end="", flush=True)

Environment Variables:
    KILO_API_KEY: Your Kilo API key (JWT token)
    KILO_API_BASE: Base URL for API (default: https://api.kilo.ai/v1)
    KILO_DEFAULT_MODEL: Default model to use (default: z-ai/glm-5:free)
"""

import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Generator, Optional, Union

import httpx

logger = logging.getLogger("kilo-gateway")

# Defaults
DEFAULT_API_BASE = "https://api.kilo.ai/v1"
DEFAULT_MODEL = "z-ai/glm-5:free"


@dataclass
class ChatMessage:
    """Represents a chat message."""

    role: str
    content: Union[str, list[dict]]
    name: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ChatResponse:
    """Represents a chat completion response."""

    id: str
    content: str
    model: str
    role: str = "assistant"
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    created: int = field(default_factory=lambda: int(time.time()))

    @classmethod
    def from_api_response(cls, data: dict) -> "ChatResponse":
        """Create ChatResponse from API response dict."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        return cls(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            content=message.get("content", ""),
            model=data.get("model", ""),
            role=message.get("role", "assistant"),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage", {}),
            created=data.get("created", int(time.time())),
        )


class KiloGatewayClient:
    """
    Client for Kilo's OpenAI-compatible gateway API.

    This client provides a simple interface for making chat completion requests
    to Kilo's gateway, including support for vision/image inputs.

    Example:
        client = KiloGatewayClient(api_key="your-jwt-token")

        # Simple chat
        response = client.chat([{"role": "user", "content": "Hello!"}])
        print(response.content)

        # With system message
        response = client.chat(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi!"},
            ]
        )

        # Vision
        with open("image.png", "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()
        response = client.chat_with_image("What's in this image?", img_base64)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 180.0,
    ):
        """
        Initialize the Kilo gateway client.

        Args:
            api_key: Kilo API key (JWT token). Defaults to KILO_API_KEY env var.
            api_base: Base URL for API. Defaults to KILO_API_BASE or https://api.kilo.ai/v1
            model: Default model to use. Defaults to KILO_DEFAULT_MODEL or z-ai/glm-5:free
            timeout: Request timeout in seconds. Default 180s for slow models.
        """
        self.api_key = api_key or os.environ.get("KILO_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key required. Set KILO_API_KEY env var or pass api_key parameter."
            )

        self.api_base = (api_base or os.environ.get("KILO_API_BASE") or DEFAULT_API_BASE).rstrip("/")
        self.model = model or os.environ.get("KILO_DEFAULT_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

        self._client = httpx.Client(timeout=timeout)
        self._async_client: Optional[httpx.AsyncClient] = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        """Close the HTTP client."""
        self._client.close()
        if self._async_client:
            self._async_client.close()

    def _headers(self) -> dict:
        """Get request headers."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def chat(
        self,
        messages: list[Union[dict, ChatMessage]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs,
    ) -> ChatResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            model: Model to use. Defaults to client's default model.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters to pass to the API.

        Returns:
            ChatResponse with the completion.

        Raises:
            httpx.HTTPStatusError: If the API returns an error.
        """
        url = f"{self.api_base}/chat/completions"

        # Normalize messages
        normalized_messages = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                normalized_messages.append(msg.to_dict())
            else:
                normalized_messages.append(msg)

        payload = {
            "model": model or self.model,
            "messages": normalized_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        logger.debug(f"POST {url} model={payload['model']}")

        response = self._client.post(url, json=payload, headers=self._headers())
        response.raise_for_status()

        data = response.json()
        return ChatResponse.from_api_response(data)

    def chat_with_image(
        self,
        prompt: str,
        image_base64: str,
        image_media_type: str = "image/png",
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """
        Send a chat request with an image (vision).

        Args:
            prompt: Text prompt/question about the image.
            image_base64: Base64-encoded image data.
            image_media_type: MIME type of the image (e.g., "image/png", "image/jpeg").
            model: Model to use. Should be a vision-capable model.
            system: Optional system message.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            ChatResponse with the completion.
        """
        messages = []

        if system:
            messages.append({"role": "system", "content": system})

        # Build user message with image
        image_url = f"data:{image_media_type};base64,{image_base64}"
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        )

        return self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def chat_with_image_url(
        self,
        prompt: str,
        image_url: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """
        Send a chat request with an image URL (vision).

        Args:
            prompt: Text prompt/question about the image.
            image_url: URL of the image.
            model: Model to use. Should be a vision-capable model.
            system: Optional system message.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            ChatResponse with the completion.
        """
        messages = []

        if system:
            messages.append({"role": "system", "content": system})

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        )

        return self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def stream_chat(
        self,
        messages: list[Union[dict, ChatMessage]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        Stream a chat completion response.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            model: Model to use. Defaults to client's default model.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters to pass to the API.

        Yields:
            Text chunks from the completion.
        """
        url = f"{self.api_base}/chat/completions"

        # Normalize messages
        normalized_messages = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                normalized_messages.append(msg.to_dict())
            else:
                normalized_messages.append(msg)

        payload = {
            "model": model or self.model,
            "messages": normalized_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }

        logger.debug(f"POST {url} model={payload['model']} (streaming)")

        with self._client.stream("POST", url, json=payload, headers=self._headers()) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data_str[:100]}")

    def list_models(self) -> list[dict]:
        """
        List available models.

        Returns:
            List of model info dicts.
        """
        url = f"{self.api_base}/models"
        response = self._client.get(url, headers=self._headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


# Convenience functions for quick usage

def quick_chat(prompt: str, model: Optional[str] = None) -> str:
    """
    Quick one-off chat completion.

    Args:
        prompt: The user prompt.
        model: Optional model override.

    Returns:
        The assistant's response text.
    """
    with KiloGatewayClient() as client:
        response = client.chat([{"role": "user", "content": prompt}], model=model)
        return response.content


def quick_vision(prompt: str, image_path: str, model: Optional[str] = None) -> str:
    """
    Quick one-off vision request.

    Args:
        prompt: Question about the image.
        image_path: Path to the image file.
        model: Optional model override (should be vision-capable).

    Returns:
        The assistant's response text.
    """
    # Read and encode image
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    image_base64 = base64.b64encode(image_bytes).decode()

    # Determine media type
    ext = image_path.lower().split(".")[-1]
    media_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/png")

    with KiloGatewayClient() as client:
        response = client.chat_with_image(prompt, image_base64, media_type, model=model)
        return response.content


if __name__ == "__main__":
    # Demo / test
    import argparse

    parser = argparse.ArgumentParser(description="Kilo Gateway Client")
    parser.add_argument("prompt", help="Prompt to send")
    parser.add_argument("--model", "-m", default=None, help="Model to use")
    parser.add_argument("--image", "-i", help="Path to image file (for vision)")
    parser.add_argument("--stream", "-s", action="store_true", help="Stream response")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    try:
        if args.image:
            print(f"Sending vision request with image: {args.image}")
            response = quick_vision(args.prompt, args.image, args.model)
            print(response)
        elif args.stream:
            print("Streaming response:")
            client = KiloGatewayClient()
            for chunk in client.stream_chat([{"role": "user", "content": args.prompt}], model=args.model):
                print(chunk, end="", flush=True)
            print()
            client.close()
        else:
            print("Sending chat request...")
            response = quick_chat(args.prompt, args.model)
            print(response)
    except Exception as e:
        print(f"Error: {e}")
        raise
