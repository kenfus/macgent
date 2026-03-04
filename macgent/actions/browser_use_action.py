"""LLM-driven multi-step browser agent using agent_browser (Playwright + stealth)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from macgent.actions.agent_browser import AgentBrowser, StealthConfig, create_stealth_config_for_site

logger = logging.getLogger("macgent.browser_task")

MAX_ELEMENTS = 80
MAX_PAGE_TEXT = 3000
MAX_HISTORY = 6

BROWSER_SYSTEM_PROMPT = """You are a web browser agent. You control a real browser to complete tasks step by step.

IMPORTANT: Respond with ONLY valid JSON. No other text before or after.

## Actions

navigate: Go to a URL
  {"reasoning": "...", "action": {"type": "navigate", "params": {"url": "https://example.com"}}}

click: Click an element by its ref from the ELEMENTS snapshot. Refs appear as [ref=eN] in the snapshot — use "@eN" to click.
  {"reasoning": "...", "action": {"type": "click", "params": {"ref": "@e1"}}}

fill: Clear an input and type into it
  {"reasoning": "...", "action": {"type": "fill", "params": {"ref": "@e2", "text": "search query"}}}

select: Select an option from a dropdown/combobox by its display text or value. Use this for <select> elements (shown as "combobox" in the snapshot).
  {"reasoning": "...", "action": {"type": "select", "params": {"ref": "@e3", "value": "4.5"}}}

press: Press a keyboard key (Enter, Tab, Escape, ArrowDown, Space, etc.)
  {"reasoning": "...", "action": {"type": "press", "params": {"key": "Enter"}}}

scroll: Scroll the page
  {"reasoning": "...", "action": {"type": "scroll", "params": {"direction": "down", "pixels": 500}}}

wait: Wait for content to load (use after navigate or after triggering slow actions)
  {"reasoning": "...", "action": {"type": "wait", "params": {"ms": 2000}}}

back: Go back in browser history
  {"reasoning": "...", "action": {"type": "back", "params": {}}}

solve_captcha: Solve a CAPTCHA challenge. Requires `captcha_type` — look at the page to identify which type it is before calling.
  captcha_type options:
    "image_grid"  — tile grid where you select images matching a category (e.g. "select all traffic lights")
    "checkbox"    — single "I'm not a robot" checkbox click
    "text"        — text/math challenge requiring typed answer (provide `answer` param)
  {"reasoning": "...", "action": {"type": "solve_captcha", "params": {"captcha_type": "image_grid"}}}
  {"reasoning": "...", "action": {"type": "solve_captcha", "params": {"captcha_type": "checkbox", "ref": "@e12"}}}
  {"reasoning": "...", "action": {"type": "solve_captcha", "params": {"captcha_type": "text", "answer": "42"}}}
  Do NOT use for cookie banners or "I Accept" buttons — click those directly.

done: Task is complete — include a summary of what was accomplished
  {"reasoning": "...", "action": {"type": "done", "params": {"summary": "Booked hotel X for dates Y-Z. Confirmation: ABC123"}}}

fail: Task cannot be completed
  {"reasoning": "...", "action": {"type": "fail", "params": {"reason": "Why it failed"}}}

## Rules

1. Output ONLY valid JSON.
2. Refs appear as [ref=eN] in ELEMENTS — use "@eN" (with @ prefix) to click, fill, or select them.
3. After navigate, wait before interacting (page needs to load).
4. **FIRST ACTION on any new page**: check ELEMENTS for cookie banners, consent dialogs, login popups, or "Sign in with Google" overlays. Dismiss them IMMEDIATELY (click "I Accept", "Accept all", "Decline", "Close", "×", or the reject/close button). These overlays block ALL other elements until dismissed.
5. For search inputs: fill the field, then press Enter.
6. For dropdown/combobox filters: use the select action, not click on individual options.
7. If stuck repeating the same action, try a completely different approach.
8. Read PAGE TEXT carefully — results and data are often already there; call done when you have what you need.
9. solve_captcha requires captcha_type. Identify the type by looking at the page first: "image_grid" = tile selection grid, "checkbox" = single I'm-not-a-robot tick, "text" = type an answer. Cookie banners and "I Accept" buttons are NOT captchas — click them directly.

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
    """Convert agent-browser accessibility snapshot to an LLM-readable element list.

    agent-browser returns: {"success": True, "data": {"refs": {"e1": {...}}, "snapshot": "..."}}
    The "snapshot" field is a hierarchical text tree with inline [ref=eN] markers — ideal for LLMs.
    """
    data = snapshot.get("data", snapshot)  # unwrap success/data envelope if present

    # Prefer the rich text snapshot — hierarchy + inline refs, most LLM-friendly
    snap_text = data.get("snapshot", "")
    if snap_text:
        lines = snap_text.splitlines()
        if len(lines) > max_elements:
            visible = lines[:max_elements]
            # Surface cookie/consent/overlay elements that appear later in the DOM
            # so the LLM can dismiss them even when truncated
            overlay_keywords = ["Accept", "accept", "consent", "Consent", "cookie", "Cookie",
                                "Decline", "decline", "privacy", "Privacy", "I agree", "I Agree"]
            overlay_lines = [
                l for l in lines[max_elements:]
                if any(kw in l for kw in overlay_keywords) and "ref=" in l
            ]
            result = "\n".join(visible)
            result += f"\n... ({len(lines) - max_elements} more elements, scroll to reveal)"
            if overlay_lines:
                result += "\n\n--- OVERLAY / CONSENT (dismiss first!) ---\n"
                result += "\n".join(overlay_lines)
            return result
        return snap_text

    # Fall back: parse refs dict into flat list
    refs = data.get("refs", {})
    if refs:
        lines = []
        for i, (ref_id, ref_data) in enumerate(refs.items()):
            if i >= max_elements:
                lines.append(f"... ({len(refs) - max_elements} more elements not shown, scroll to reveal)")
                break
            role = (ref_data.get("role") or "").lower()
            name = (ref_data.get("name") or "").strip()[:70]
            value = (ref_data.get("value") or "").strip()[:50]
            line = f"[{role}] @{ref_id}"
            if name:
                line += f' "{name}"'
            if value:
                line += f' (value: "{value}")'
            lines.append(line)
        return "\n".join(lines)

    # Legacy fallback: old elements list format
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


def _human_delay(lo: float = 0.4, hi: float = 1.2) -> None:
    """Random human-like pause between actions."""
    import random
    import time as _t
    _t.sleep(lo + random.random() * (hi - lo))


def _execute_action(browser: AgentBrowser, action: dict, config: Any = None) -> str:
    """Execute one browser action and return a result string."""
    t = action["type"]
    p = action.get("params", {})
    try:
        if t == "navigate":
            url = p["url"]
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            browser.open(url)
            browser.wait(2000)
            # Inject fingerprint spoofing on every navigation
            try:
                browser.inject_fingerprint_spoof()
            except Exception:
                pass
            _human_delay(1.0, 2.5)  # Simulate page-reading pause after load
            return f"Navigated to {url}"
        elif t == "click":
            _human_delay(0.3, 0.9)
            return browser.click(p["ref"])
        elif t == "select":
            _human_delay(0.3, 0.8)
            browser.select(p["ref"], p.get("value", ""))
            return f"Selected '{p.get('value', '')}' in {p['ref']}"
        elif t == "fill":
            _human_delay(0.3, 0.7)
            browser.fill(p["ref"], p.get("text", ""))
            return f"Filled {p['ref']}"
        elif t == "type":
            _human_delay(0.3, 0.7)
            browser.type_text(p["ref"], p.get("text", ""))
            return f"Typed into {p['ref']}"
        elif t == "press":
            _human_delay(0.2, 0.5)
            return browser.press(p.get("key", "Enter"))
        elif t == "scroll":
            _human_delay(0.4, 1.0)
            return browser.scroll(p.get("direction", "down"), int(p.get("pixels", 500)))
        elif t == "wait":
            return browser.wait(int(p.get("ms", 1000)))
        elif t == "back":
            _human_delay(0.3, 0.8)
            return browser.back()
        elif t == "solve_captcha":
            import os
            import time as _time

            captcha_type = p.get("captcha_type", "").strip()
            if not captcha_type:
                return "ERROR: solve_captcha requires 'captcha_type': image_grid | checkbox | text"

            # --- checkbox: just click the ref or find the iframe checkbox ---
            if captcha_type == "checkbox":
                ref = p.get("ref", "")
                if ref:
                    browser.click(ref)
                    return "solve_captcha: checkbox clicked"
                # Try to find reCAPTCHA checkbox iframe and click it
                try:
                    browser.eval_js(
                        "document.querySelector('iframe[title*=\"captcha\"],"
                        "iframe[src*=\"recaptcha\"],iframe[src*=\"captcha\"]')"
                        "?.contentDocument?.querySelector('#recaptcha-anchor')?.click()"
                    )
                except Exception:
                    pass
                return "solve_captcha: checkbox click attempted (provide ref if it fails)"

            # --- text: type the answer into the active/visible input ---
            if captcha_type == "text":
                answer = p.get("answer", "").strip()
                if not answer:
                    return "ERROR: solve_captcha text type requires 'answer' param"
                ref = p.get("ref", "")
                if ref:
                    browser.fill(ref, answer)
                else:
                    browser.eval_js(
                        f"(document.querySelector('input[type=text],input[type=number]')"
                        f" || document.activeElement).value = {json.dumps(answer)}"
                    )
                return f"solve_captcha: text answer '{answer}' entered"

            # --- image_grid: 3-pass pipeline via vision model ---
            if captcha_type == "image_grid":
                import httpx as _httpx
                from macgent.actions.captcha_solver import solve_image_grid_captcha, CaptchaResult

                screenshot_path = "/tmp/browser_captcha_solve.png"
                browser.screenshot(screenshot_path)

                kilo_key = getattr(config, "kilo_api_key", "") or os.getenv("KILO_API_KEY", "")
                if not kilo_key:
                    return "ERROR: solve_captcha requires KILO_API_KEY in config or environment"

                def _kilo_vision(image_b64: str, prompt: str, max_tokens: int = 16384) -> str:
                    resp = _httpx.post(
                        "https://api.kilo.ai/api/gateway/chat/completions",
                        json={
                            "model": "moonshotai/kimi-k2.5:free",
                            "max_tokens": max_tokens,
                            "messages": [{"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                                {"type": "text", "text": prompt},
                            ]}],
                        },
                        headers={"Authorization": f"Bearer {kilo_key}", "Content-Type": "application/json"},
                        timeout=240,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data["choices"][0]["message"]
                    return (msg.get("content") or msg.get("reasoning_content") or "").strip()

                captcha_result: CaptchaResult = solve_image_grid_captcha(screenshot_path, _kilo_vision, debug_dir="/tmp")

                if not captcha_result.solved:
                    return f"solve_captcha: image_grid unsolved — {captcha_result.description}"

                for cx, cy in captcha_result.clicks:
                    browser.mouse_move(cx, cy)
                    _time.sleep(0.05)
                    browser.mouse_down()
                    _time.sleep(0.05)
                    browser.mouse_up()
                    _time.sleep(0.2)

                _time.sleep(0.5)
                try:
                    browser.eval_js("document.querySelector('button').click()")
                except Exception:
                    pass

                return f"solve_captcha: image_grid solved — {len(captcha_result.clicks)} tile(s) clicked"

            return f"ERROR: unknown captcha_type '{captcha_type}' — use image_grid | checkbox | text"
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
        headed = bool(getattr(config, "browser_headed", True))  # Default headed — headless is trivially detected
        # Extract domain for site-specific stealth config
        import re as _re
        _domain_match = _re.search(r"https?://([^/]+)", task_desc)
        _domain = _domain_match.group(1) if _domain_match else ""
        stealth_cfg = create_stealth_config_for_site(_domain)
        stealth_cfg.headed = headed
        browser = AgentBrowser(stealth_cfg)
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

            # --- DataDome / hard-block detection ---
            # "Access is temporarily restricted" = DataDome IP/device ban, not solvable
            _BLOCK_PHRASES = [
                "access is temporarily restricted",
                "we detected unusual activity",
                "unusual activity from your device",
            ]
            if any(phrase in page_text.lower() for phrase in _BLOCK_PHRASES):
                result["blocked_reason"] = "datadome_ip_ban"
                result["url"] = url
                logger.warning("DataDome hard block detected on %s — stopping", url)
                break

            # --- Think ---
            action = _parse_action(
                llm.chat(
                    messages=[{"role": "user", "content": _build_user_message(
                        task_desc, url, title, page_text, snapshot, history
                    )}],
                    system=BROWSER_SYSTEM_PROMPT,
                    max_tokens=4096,
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
            outcome = _execute_action(browser, action, config)
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
