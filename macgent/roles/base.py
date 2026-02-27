"""Minimal base role with unified LLM call + markdown context helper."""

from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from macgent.reasoning.llm_client import build_text_fallback_client

logger = logging.getLogger("macgent.roles")


class BaseRole:
    role_name: str = "base"

    def __init__(self, config, db, memory):
        self.config = config
        self.db = db
        self.memory = memory
        self._llm = build_text_fallback_client(config)

    def call_llm(self, messages: list[dict], system: str = "", max_tokens: int = 2048, temperature: float = 0.0) -> str:
        content = self._llm.chat(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not content or not content.strip():
            raise RuntimeError("LLM returned empty response")
        return content

    @staticmethod
    def combine_markdown_context(parts: Iterable[tuple[str, str]]) -> str:
        """Combine markdown sections into one prompt string."""
        chunks: list[str] = []
        for title, body in parts:
            b = (body or "").strip()
            if not b:
                continue
            chunks.append(f"# {title}\n\n{b}")
        return "\n\n---\n\n".join(chunks)

    def parse_json(self, text: str) -> dict | None:
        text = text.strip()
        if "<think>" in text:
            parts = text.split("</think>")
            text = parts[-1].strip() if len(parts) > 1 else text

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None

    def get_system_prompt(self, task_id: str | None = None, task_description: str = "") -> str:
        return self.memory.build_context(self.db, self.role_name, task_id, task_description)

    def tick(self):
        raise NotImplementedError
