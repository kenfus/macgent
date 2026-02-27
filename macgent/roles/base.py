"""Base role class with unified LLM fallback routing."""

import json
import re
import logging
from macgent.reasoning.llm_client import build_text_fallback_client

logger = logging.getLogger("macgent.roles")


class BaseRole:
    """Shared parent for Manager, Worker, and Stakeholder roles."""

    role_name: str = "base"

    def __init__(self, config, db, memory):
        self.config = config
        self.db = db
        self.memory = memory
        self._llm = build_text_fallback_client(config)

    def call_llm(self, messages: list[dict], system: str = "",
                 max_tokens: int = 2048, temperature: float = 0.0) -> str:
        """Call LLM through unified primary/fallback offer chain."""
        # Log the outgoing prompt at DEBUG level (visible in log file)
        last_msg = messages[-1]["content"] if messages else ""
        logger.debug(
            f"[{self.role_name}] LLM call | chain={self.config.get_text_offer_chain()} | "
            f"msgs={len(messages)} | last_msg={last_msg[:200]}"
        )

        content = self._llm.chat(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not content or not content.strip():
            raise RuntimeError("LLM returned empty response")
        return content

    def parse_json(self, text: str) -> dict | None:
        """Extract JSON from LLM output (reuses proven strategies from reasoner.py)."""
        text = text.strip()

        # Strip thinking tokens
        if "<think>" in text:
            parts = text.split("</think>")
            text = parts[-1].strip() if len(parts) > 1 else text

        # Strategy 1: Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Markdown code blocks
        if "```" in text:
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # Strategy 3: First { to last }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # Strategy 4: Balanced braces
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

        # Strategy 5: Fix common issues
        if start >= 0 and end > start:
            candidate = text[start:end]
            fixed = candidate.replace("'", '"')
            fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        return None

    def get_system_prompt(self, task_id: str | None = None,
                          task_description: str = "") -> str:
        """Build full system prompt with soul + memory context."""
        context = self.memory.build_context(
            self.db, self.role_name, task_id, task_description,
        )
        return context

    def tick(self):
        """Override in subclasses. Called each heartbeat cycle."""
        raise NotImplementedError
