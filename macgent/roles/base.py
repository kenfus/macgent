"""Base role class with LLM fallback chain support."""

import json
import re
import logging
import httpx

logger = logging.getLogger("macgent.roles")


class BaseRole:
    """Shared parent for Manager, Worker, and Stakeholder roles."""

    role_name: str = "base"

    def __init__(self, config, db, memory):
        self.config = config
        self.db = db
        self.memory = memory
        self.model_chain = config.get_model_chain(self.role_name)
        self._http = httpx.Client(timeout=180.0)

    def call_llm(self, messages: list[dict], system: str = "",
                 max_tokens: int = 2048, temperature: float = 0.0) -> str:
        """Call LLM with automatic fallback on 429/500/timeout."""
        # Log the outgoing prompt at DEBUG level (visible in log file)
        last_msg = messages[-1]["content"] if messages else ""
        logger.debug(
            f"[{self.role_name}] LLM call | model_chain={self.model_chain[0]}... | "
            f"msgs={len(messages)} | last_msg={last_msg[:200]}"
        )

        last_error = None
        for model in self.model_chain:
            try:
                result = self._call_openai(model, messages, system, max_tokens, temperature)
                logger.debug(f"[{self.role_name}] LLM response ({model}): {result[:300]}")
                return result
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_error = e
                status = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
                logger.warning(f"[{self.role_name}] Model {model} failed (status={status}): {e}")
                continue
            except Exception as e:
                last_error = e
                logger.error(f"[{self.role_name}] Model {model} unexpected error: {e}")
                continue

        raise RuntimeError(f"All models failed for {self.role_name}. Last error: {last_error}")

    def _call_openai(self, model: str, messages: list[dict], system: str,
                     max_tokens: int, temperature: float) -> str:
        """Call OpenRouter/OpenAI-compatible API."""
        api_base = self.config.reasoning_api_base.rstrip("/")
        url = f"{api_base}/chat/completions"

        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload = {
            "model": model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.reasoning_api_key}",
        }

        logger.debug(f"[{self.role_name}] POST {url} model={model}")
        resp = self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise RuntimeError(f"Model {model} returned empty response")
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
