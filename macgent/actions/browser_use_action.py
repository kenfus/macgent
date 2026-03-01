"""LLM-driven multi-step browser agent using agent_browser (Playwright + stealth)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from macgent.actions.agent_browser import AgentBrowser, StealthConfig

logger = logging.getLogger("macgent.browser_task")

MAX_ELEMENTS = 80
MAX_PAGE_TEXT = 3000
MAX_HISTORY = 6

BROWSER_SYSTEM_PROMPT = """You are a web browser agent. You control a real browser to complete tasks step by step.

IMPORTANT: Respond with ONLY valid JSON. No other text before or after.

## Actions

navigate: Go to a URL
  {"reasoning": "...", "action": {"type": "navigate", "params": {"url": "https://example.com"}}}

click: Click an element by its @ref from the ELEMENTS list
  {"reasoning": "...", "action": {"type": "click", "params": {"ref": "@123"}}}

fill: Clear an input and type into it
  {"reasoning": "...", "action": {"type": "fill", "params": {"ref": "@124", "text": "search query"}}}

press: Press a keyboard key (Enter, Tab, Escape, ArrowDown, Space, etc.)
  {"reasoning": "...", "action": {"type": "press", "params": {"key": "Enter"}}}

scroll: Scroll the page
  {"reasoning": "...", "action": {"type": "scroll", "params": {"direction": "down", "pixels": 500}}}

wait: Wait for content to load (use after navigate or after triggering slow actions)
  {"reasoning": "...", "action": {"type": "wait", "params": {"ms": 2000}}}

back: Go back in browser history
  {"reasoning": "...", "action": {"type": "back", "params": {}}}

done: Task is complete — include a summary of what was accomplished
  {"reasoning": "...", "action": {"type": "done", "params": {"summary": "Booked hotel X for dates Y-Z. Confirmation: ABC123"}}}

fail: Task cannot be completed
  {"reasoning": "...", "action": {"type": "fail", "params": {"reason": "Why it failed"}}}

## Rules

1. Output ONLY valid JSON.
2. Use @ref values from ELEMENTS to click/fill — they are exact Playwright element references.
3. After navigate, wait before interacting (page needs to load).
4. For search inputs: fill the field, then press Enter.
5. Dismiss cookie/consent/popup dialogs immediately — click reject/close/decline first.
6. If stuck repeating the same action, try a completely different approach.
7. Read PAGE TEXT carefully — results and data are often already there; call done when you have what you need.

## Response format

{"reasoning": "brief step-by-step thinking", "action": {"type": "...", "params": {...}}}
"""


def _get_run_dir(config: Any, capture_artifacts: bool) -> Path | None:
    if not capture_artifacts:
        return None
    workspace = Path(getattr(config, "workspace_dir", "workspace"))
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = workspace / "browser_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _clean_js_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        try:
            return json.loads(cleaned)
        except Exception:
            return cleaned.strip('"')
    return cleaned


def _format_snapshot(snapshot: dict, max_elements: int = MAX_ELEMENTS) -> str:
    """Convert agent-browser accessibility snapshot to an LLM-readable element list."""
    elements = snapshot.get("elements", [])[:max_elements]
    lines = []
    for el in elements:
        ref = el.get("ref", "")
        role = (el.get("role") or el.get("tagName", "")).lower()
        name = (el.get("name") or "").strip()[:70]
        value = (el.get("value") or "").strip()[:50]

        line = f"[{role}] {ref}"
        if name:
            line += f' "{name}"'
        if value:
            line += f' (value: "{value}")'
        lines.append(line)

    truncated = len(snapshot.get("elements", [])) - max_elements
    if truncated > 0:
        lines.append(f"... ({truncated} more elements not shown, scroll to reveal)")
    return "\n".join(lines)


def _build_user_message(
    task: str,
    url: str,
    title: str,
    page_text: str,
    snapshot: dict,
    history: list[dict],
) -> str:
    parts = [f"TASK: {task}"]

    if history:
        parts.append("\nRECENT STEPS:")
        for h in history[-MAX_HISTORY:]:
            result_preview = (h.get("result") or "")[:100]
            params_preview = json.dumps(h.get("params", {}), ensure_ascii=False)[:80]
            parts.append(f"  {h['type']} {params_preview} -> {result_preview}")

    parts.append(f"\nCURRENT STATE:")
    parts.append(f"  URL: {url or '(not navigated yet)'}")
    parts.append(f"  Title: {title or '(none)'}")

    elements_text = _format_snapshot(snapshot)
    if elements_text:
        parts.append(f"\nELEMENTS (use @ref to interact):\n{elements_text}")
    else:
        parts.append("\nELEMENTS: (none visible — navigate first or scroll)")

    if page_text:
        parts.append(f"\nPAGE TEXT:\n{page_text[:MAX_PAGE_TEXT]}")

    parts.append("\nWhat is the next action? Respond with JSON only.")
    return "\n".join(parts)


def _parse_action(text: str) -> dict:
    """Extract a {type, params, reasoning} action dict from raw LLM output."""
    text = text.strip()
    # Strip thinking tokens (DeepSeek-R1, Qwen3, etc.)
    if "<think>" in text:
        text = text.split("</think>")[-1].strip()

    for attempt in [
        lambda t: json.loads(t),
        lambda t: json.loads(re.search(r"```(?:json)?\s*(.*?)\s*```", t, re.DOTALL).group(1)),
        lambda t: json.loads(t[t.find("{"):t.rfind("}") + 1]),
    ]:
        try:
            data = attempt(text)
            action_data = data.get("action", data)
            return {
                "type": action_data.get("type", "wait"),
                "params": action_data.get("params", {}),
                "reasoning": data.get("reasoning", ""),
            }
        except Exception:
            continue

    logger.warning("Could not parse LLM action: %s", text[:200])
    return {"type": "wait", "params": {"ms": 2000}, "reasoning": "parse_error"}


def _execute_action(browser: AgentBrowser, action: dict) -> str:
    """Execute one browser action and return a result string."""
    t = action["type"]
    p = action.get("params", {})
    try:
        if t == "navigate":
            url = p["url"]
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            browser.open(url)
            browser.wait(1500)
            return f"Navigated to {url}"
        elif t == "click":
            return browser.click(p["ref"])
        elif t == "fill":
            browser.fill(p["ref"], p.get("text", ""))
            return f"Filled {p['ref']}"
        elif t == "type":
            browser.type_text(p["ref"], p.get("text", ""))
            return f"Typed into {p['ref']}"
        elif t == "press":
            return browser.press(p.get("key", "Enter"))
        elif t == "scroll":
            return browser.scroll(p.get("direction", "down"), int(p.get("pixels", 500)))
        elif t == "wait":
            return browser.wait(int(p.get("ms", 1000)))
        elif t == "back":
            return browser.back()
        else:
            return f"Unknown action: {t}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def _build_browser_llm(config: Any):
    from macgent.reasoning.llm_client import resolve_offers, FallbackLLMClient
    chain = (
        config.get_browser_text_offer_chain()
        if hasattr(config, "get_browser_text_offer_chain")
        else config.get_text_offer_chain()
    )
    offers = resolve_offers(config, chain, modality="text")
    policy = config.get_error_policy() if hasattr(config, "get_error_policy") else {}
    return FallbackLLMClient(offers, error_policy=policy)


def run_browser_task(
    config: Any,
    task_desc: str,
    mode: str | None = None,
    max_steps: int | None = None,
    capture_artifacts: bool = True,
) -> str:
    """LLM-driven observe→think→act browser loop. Returns a structured JSON result string."""
    max_steps = int(max_steps or getattr(config, "max_steps", 20))
    run_dir = _get_run_dir(config, capture_artifacts)

    result: dict[str, Any] = {
        "backend": "agent_browser",
        "task": task_desc,
        "solved": False,
        "blocked_reason": None,
        "steps": 0,
        "summary": None,
        "url": None,
        "artifact_dir": str(run_dir) if run_dir else None,
    }

    llm = _build_browser_llm(config)

    browser: AgentBrowser | None = None
    try:
        headed = bool(getattr(config, "browser_headed", False))
        browser = AgentBrowser(StealthConfig(headed=headed))
        browser.start()

        history: list[dict] = []
        url, title, page_text, snapshot = "", "", "", {}
        step = 0

        for step in range(1, max_steps + 1):
            # --- Observe ---
            try:
                url = _clean_js_value(browser.get_url()) or url
                title = _clean_js_value(browser.get_title()) or title
                page_text = (_clean_js_value(browser.get_text()) or "")[:MAX_PAGE_TEXT]
                snapshot = browser.snapshot(interactive=True)
            except Exception as e:
                logger.debug("observe error step %d: %s", step, e)

            # --- Think ---
            action = _parse_action(
                llm.chat(
                    messages=[{"role": "user", "content": _build_user_message(
                        task_desc, url, title, page_text, snapshot, history
                    )}],
                    system=BROWSER_SYSTEM_PROMPT,
                    max_tokens=512,
                    temperature=0.0,
                )
            )
            logger.info(
                "browser step=%d/%d action=%s reasoning=%s",
                step, max_steps, action["type"], action.get("reasoning", "")[:80],
            )

            # --- Terminal ---
            if action["type"] == "done":
                result["solved"] = True
                result["summary"] = action.get("params", {}).get("summary", "")
                result["url"] = url
                history.append({**action, "result": "DONE"})
                break
            if action["type"] == "fail":
                result["blocked_reason"] = action.get("params", {}).get("reason", "agent_failed")
                result["url"] = url
                history.append({**action, "result": "FAILED"})
                break

            # --- Act ---
            outcome = _execute_action(browser, action)
            logger.debug("step %d result: %s", step, outcome[:120])
            history.append({**action, "result": outcome})

            if run_dir and step % 3 == 0:
                try:
                    browser.screenshot(str(run_dir / f"step_{step:03d}.png"))
                except Exception:
                    pass
        else:
            result["blocked_reason"] = "max_steps_exceeded"
            result["url"] = url

        result["steps"] = step
        if not result["url"]:
            result["url"] = url

        if run_dir:
            try:
                browser.screenshot(str(run_dir / "final.png"), full_page=True)
            except Exception:
                pass
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))

        logger.info(
            "browser_task_done solved=%s steps=%d url=%s",
            result["solved"], result["steps"], result["url"],
        )
        return json.dumps(result)

    except Exception as e:
        result["blocked_reason"] = f"browser_error:{type(e).__name__}"
        result["error"] = str(e)
        logger.error("browser_task_failed: %s", e)
        if run_dir:
            try:
                (run_dir / "result.json").write_text(json.dumps(result, indent=2))
            except Exception:
                pass
        return json.dumps(result)

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
