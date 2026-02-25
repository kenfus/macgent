#!/usr/bin/env python3
"""
Kilo Wrapper - Unified interface for Kilo gateway API and CLI.

This module provides a single interface that can route requests to either:
1. Kilo's gateway API (direct HTTP calls)
2. Kilo CLI (subprocess calls to `kilo` command)
3. Auto mode (try gateway first, fallback to CLI)

Usage:
    from kilo_wrapper import KiloWrapper

    # Auto mode (gateway with CLI fallback)
    kilo = KiloWrapper()
    response = kilo.complete("Hello!")

    # Gateway only
    kilo = KiloWrapper(backend="gateway")
    response = kilo.complete("Hello!")

    # CLI only
    kilo = KiloWrapper(backend="cli")
    response = kilo.complete("Hello!")

    # Vision
    response = kilo.complete("Describe this", image_path="/tmp/screenshot.png")

Environment Variables:
    KILO_API_KEY: Your Kilo API key (JWT token) for gateway
    KILO_API_BASE: Base URL for API (default: https://api.kilo.ai/v1)
    KILO_DEFAULT_MODEL: Default model to use
    KILO_BACKEND: Default backend ("gateway", "cli", or "auto")
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Generator, Optional, Union

from gateway_client import KiloGatewayClient, ChatResponse

logger = logging.getLogger("kilo-wrapper")


class Backend(Enum):
    """Available backends for Kilo."""

    GATEWAY = "gateway"  # Use Kilo gateway API directly
    CLI = "cli"  # Use Kilo CLI via subprocess
    AUTO = "auto"  # Try gateway first, fallback to CLI


@dataclass
class KiloConfig:
    """Configuration for Kilo wrapper."""

    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    backend: Backend = Backend.AUTO
    timeout: float = 180.0
    cli_path: str = "kilo"  # Path to kilo CLI

    @classmethod
    def from_env(cls) -> "KiloConfig":
        """Create config from environment variables."""
        backend_str = os.environ.get("KILO_BACKEND", "auto").lower()
        backend_map = {
            "gateway": Backend.GATEWAY,
            "cli": Backend.CLI,
            "auto": Backend.AUTO,
        }
        backend = backend_map.get(backend_str, Backend.AUTO)

        return cls(
            api_key=os.environ.get("KILO_API_KEY"),
            api_base=os.environ.get("KILO_API_BASE"),
            model=os.environ.get("KILO_DEFAULT_MODEL"),
            backend=backend,
        )


class KiloWrapper:
    """
    Unified wrapper for Kilo gateway API and CLI.

    This class provides a consistent interface for making completion requests,
    abstracting away whether the backend is the gateway API or CLI.

    Example:
        # Simple usage with defaults
        kilo = KiloWrapper()
        response = kilo.complete("What is 2+2?")
        print(response.content)

        # With image
        response = kilo.complete(
            "Describe this screenshot",
            image_path="/tmp/screen.png"
        )

        # Streaming
        for chunk in kilo.stream("Tell me a story"):
            print(chunk, end="", flush=True)

        # Specify backend
        kilo = KiloWrapper(backend=Backend.GATEWAY)
        response = kilo.complete("Hello!")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        backend: Union[Backend, str] = Backend.AUTO,
        timeout: float = 180.0,
        cli_path: str = "kilo",
    ):
        """
        Initialize the Kilo wrapper.

        Args:
            api_key: Kilo API key for gateway. Defaults to KILO_API_KEY env var.
            api_base: Base URL for gateway API.
            model: Default model to use.
            backend: Backend to use ("gateway", "cli", or "auto").
            timeout: Request timeout in seconds.
            cli_path: Path to kilo CLI executable.
        """
        # Normalize backend
        if isinstance(backend, str):
            backend = Backend(backend.lower())

        self.config = KiloConfig(
            api_key=api_key or os.environ.get("KILO_API_KEY"),
            api_base=api_base or os.environ.get("KILO_API_BASE"),
            model=model or os.environ.get("KILO_DEFAULT_MODEL"),
            backend=backend,
            timeout=timeout,
            cli_path=cli_path,
        )

        self._gateway_client: Optional[KiloGatewayClient] = None

    @property
    def gateway_client(self) -> KiloGatewayClient:
        """Get or create the gateway client."""
        if self._gateway_client is None:
            self._gateway_client = KiloGatewayClient(
                api_key=self.config.api_key,
                api_base=self.config.api_base,
                model=self.config.model,
                timeout=self.config.timeout,
            )
        return self._gateway_client

    def _check_cli_available(self) -> bool:
        """Check if Kilo CLI is available."""
        return shutil.which(self.config.cli_path) is not None

    def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
        image_base64: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        backend: Optional[Union[Backend, str]] = None,
    ) -> ChatResponse:
        """
        Complete a prompt using the configured backend.

        Args:
            prompt: The user prompt.
            model: Model to use (optional override).
            system: System message (optional).
            image_path: Path to image file for vision requests.
            image_base64: Base64-encoded image data (alternative to image_path).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            backend: Backend override for this request.

        Returns:
            ChatResponse with the completion.

        Raises:
            RuntimeError: If no backend is available.
        """
        # Normalize backend
        if isinstance(backend, str):
            backend = Backend(backend.lower())
        backend = backend or self.config.backend

        # Prepare image data if needed
        img_b64 = image_base64
        img_media_type = "image/png"
        if image_path and not img_b64:
            with open(image_path, "rb") as f:
                img_bytes = f.read()
            img_b64 = base64.b64encode(img_bytes).decode()

            # Determine media type
            ext = image_path.lower().split(".")[-1]
            media_types = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }
            img_media_type = media_types.get(ext, "image/png")

        # Try gateway first if auto or gateway
        if backend in (Backend.GATEWAY, Backend.AUTO):
            try:
                return self._complete_gateway(
                    prompt=prompt,
                    model=model,
                    system=system,
                    image_base64=img_b64,
                    image_media_type=img_media_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                if backend == Backend.AUTO:
                    logger.warning(f"Gateway failed, falling back to CLI: {e}")
                else:
                    raise

        # Use CLI
        if backend in (Backend.CLI, Backend.AUTO):
            if not self._check_cli_available():
                if backend == Backend.AUTO:
                    raise RuntimeError("Gateway failed and Kilo CLI not available")
                raise RuntimeError("Kilo CLI not available")

            return self._complete_cli(
                prompt=prompt,
                model=model,
                image_path=image_path,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        raise RuntimeError(f"Unknown backend: {backend}")

    def _complete_gateway(
        self,
        prompt: str,
        model: Optional[str],
        system: Optional[str],
        image_base64: Optional[str],
        image_media_type: str,
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Complete using gateway API."""
        if image_base64:
            return self.gateway_client.chat_with_image(
                prompt=prompt,
                image_base64=image_base64,
                image_media_type=image_media_type,
                model=model,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return self.gateway_client.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    def _complete_cli(
        self,
        prompt: str,
        model: Optional[str],
        image_path: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Complete using Kilo CLI."""
        cmd = [self.config.cli_path, "run", prompt, "--format", "json", "--auto"]

        if model:
            cmd.extend(["-m", model])

        if image_path:
            cmd.extend(["-f", image_path])

        logger.debug(f"Running CLI: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Kilo CLI failed: {result.stderr}")

        # Parse JSON output
        response_text = ""
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "text":
                    response_text += event.get("part", {}).get("text", "")
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse CLI output: {line[:100]}")

        return ChatResponse(
            id=f"cli-{int(time.time())}",
            content=response_text,
            model=model or self.config.model or "kilo-cli",
        )

    def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        backend: Optional[Union[Backend, str]] = None,
    ) -> Generator[str, None, None]:
        """
        Stream a completion response.

        Note: Streaming is only supported via the gateway backend.
        CLI backend will fall back to non-streaming.

        Args:
            prompt: The user prompt.
            model: Model to use.
            system: System message.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens.
            backend: Backend override.

        Yields:
            Text chunks from the completion.
        """
        if isinstance(backend, str):
            backend = Backend(backend.lower())
        backend = backend or self.config.backend

        if backend == Backend.CLI:
            # CLI doesn't support streaming in the same way
            response = self._complete_cli(
                prompt=prompt,
                model=model,
                image_path=None,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            yield response.content
            return

        # Use gateway streaming
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        yield from self.gateway_client.stream_chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def set_backend(self, backend: Union[Backend, str]) -> None:
        """Set the default backend."""
        if isinstance(backend, str):
            backend = Backend(backend.lower())
        self.config.backend = backend

    def close(self) -> None:
        """Close any open clients."""
        if self._gateway_client:
            self._gateway_client.close()
            self._gateway_client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Async support
class AsyncKiloWrapper:
    """
    Async version of KiloWrapper.

    This provides async methods for use in async contexts.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        backend: Union[Backend, str] = Backend.AUTO,
        timeout: float = 180.0,
    ):
        if isinstance(backend, str):
            backend = Backend(backend.lower())

        self.config = KiloConfig(
            api_key=api_key or os.environ.get("KILO_API_KEY"),
            api_base=api_base or os.environ.get("KILO_API_BASE"),
            model=model or os.environ.get("KILO_DEFAULT_MODEL"),
            backend=backend,
            timeout=timeout,
        )

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
        image_base64: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """
        Async completion using CLI subprocess.

        Note: For true async HTTP, use KiloGatewayClient directly with httpx.AsyncClient.
        """
        # For now, use CLI in async context
        # A full implementation would use httpx async client for gateway
        import asyncio

        loop = asyncio.get_event_loop()
        wrapper = KiloWrapper(
            api_key=self.config.api_key,
            api_base=self.config.api_base,
            model=self.config.model,
            backend=Backend.CLI,  # Use CLI for async
            timeout=self.config.timeout,
        )
        return await loop.run_in_executor(
            None,
            lambda: wrapper.complete(
                prompt=prompt,
                model=model,
                system=system,
                image_path=image_path,
                image_base64=image_base64,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )


# Convenience functions
def complete(prompt: str, **kwargs) -> str:
    """
    Quick completion helper.

    Args:
        prompt: The prompt to complete.
        **kwargs: Additional arguments passed to KiloWrapper.complete().

    Returns:
        The completion text.
    """
    with KiloWrapper() as kilo:
        response = kilo.complete(prompt, **kwargs)
        return response.content


def vision(prompt: str, image_path: str, **kwargs) -> str:
    """
    Quick vision helper.

    Args:
        prompt: Question about the image.
        image_path: Path to the image file.
        **kwargs: Additional arguments passed to KiloWrapper.complete().

    Returns:
        The completion text.
    """
    with KiloWrapper() as kilo:
        response = kilo.complete(prompt, image_path=image_path, **kwargs)
        return response.content


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kilo Wrapper")
    parser.add_argument("prompt", help="Prompt to send")
    parser.add_argument("--model", "-m", default=None, help="Model to use")
    parser.add_argument("--backend", "-b", choices=["gateway", "cli", "auto"], default="auto")
    parser.add_argument("--image", "-i", help="Path to image file (for vision)")
    parser.add_argument("--stream", "-s", action="store_true", help="Stream response")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    try:
        with KiloWrapper(backend=args.backend) as kilo:
            if args.stream:
                print("Streaming response:")
                for chunk in kilo.stream(args.prompt, model=args.model):
                    print(chunk, end="", flush=True)
                print()
            else:
                print(f"Sending request via {args.backend}...")
                response = kilo.complete(
                    args.prompt,
                    model=args.model,
                    image_path=args.image,
                )
                print(response.content)
    except Exception as e:
        print(f"Error: {e}")
        raise
