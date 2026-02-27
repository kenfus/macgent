"""Hybrid browser fallback adapter used by dispatcher and CLI.

This module provides a stable `run_browser_task` function for browser task delegation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from macgent.actions.agent_browser import AgentBrowser, StealthConfig, find_element_by
from macgent.reasoning.browser_signals import detect_browser_blockers
from macgent.reasoning.llm_client import FallbackLLMClient, resolve_offers
from macgent.reasoning.vision import describe_screenshot

logger = logging.getLogger("macgent.browser_task")


def _get_run_dir(config: Any, capture_artifacts: bool) -> Path | None:
    if not capture_artifacts:
        return None
    workspace = Path(getattr(config, "workspace_dir", "workspace"))
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = workspace / "browser_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _extract_url(task_desc: str) -> str | None:
    match = re.search(r"https?://[^\s)]+", task_desc)
    if match:
        return match.group(0)
    return None


def _clean_js_value(value: str | None) -> str | None:
    """Normalize quoted eval-js string return values."""
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        try:
            return json.loads(cleaned)
        except Exception:
            return cleaned.strip('"')
    return cleaned


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from model output."""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


def _run_llm_captcha_action(
    browser: AgentBrowser,
    reasoning_client: FallbackLLMClient,
    task_desc: str,
    snapshot: dict[str, Any],
    clues: str,
) -> str | None:
    """Ask reasoning model for one captcha action and execute it."""
    elements = snapshot.get("elements", [])[:80]
    el_lines = [
        f"{el.get('ref','')} | role={el.get('role','')} | name={el.get('name','')}"
        for el in elements
    ]
    prompt = (
        "You are controlling a browser to solve one captcha step.\n"
        "Return JSON only with exactly one action from:\n"
        "click, double_click, drag, press, mouse_wheel.\n"
        "Schema:\n"
        '{"action":"click","ref":"@e1"} OR '
        '{"action":"drag","from":"@e1","to":"@e2"} OR '
        '{"action":"press","key":"Tab"} OR '
        '{"action":"mouse_wheel","dy":500,"dx":0}\n\n'
        f"Task: {task_desc}\n"
        f"Vision clues: {clues[:1000]}\n"
        "Interactive elements:\n"
        + "\n".join(el_lines)
    )
    raw = reasoning_client.chat(
        messages=[{"role": "user", "content": prompt}],
        system="Return JSON only.",
        max_tokens=300,
        temperature=0.0,
    )
    data = _extract_json_obj(raw) or {}
    action = str(data.get("action", "")).strip()

    if action == "click" and data.get("ref"):
        browser.click(str(data["ref"]))
        return "llm:click"
    if action == "double_click" and data.get("ref"):
        browser.double_click(str(data["ref"]))
        return "llm:double_click"
    if action == "drag" and data.get("from") and data.get("to"):
        browser.drag(str(data["from"]), str(data["to"]))
        return "llm:drag"
    if action == "press" and data.get("key"):
        browser.press(str(data["key"]))
        return "llm:press"
    if action == "mouse_wheel":
        dy = int(data.get("dy", 300))
        dx = int(data.get("dx", 0))
        browser.mouse_wheel(dy, dx)
        return "llm:mouse_wheel"
    return None


def _run_kilo_cli_captcha_action(
    browser: AgentBrowser,
    task_desc: str,
    snapshot: dict[str, Any],
    clues: str,
) -> str | None:
    """Last-resort captcha action through local KILO CLI wrapper (GLM-5)."""
    try:
        if "scripts" not in sys.path:
            sys.path.append("scripts")
        from kilo_wrapper import KiloWrapper, Backend  # type: ignore
    except Exception:
        return None

    elements = snapshot.get("elements", [])[:80]
    el_lines = [
        f"{el.get('ref','')} | role={el.get('role','')} | name={el.get('name','')}"
        for el in elements
    ]
    prompt = (
        "Return JSON only for one browser action.\n"
        "Allowed: click, double_click, drag, press, mouse_wheel.\n"
        'Schema: {"action":"click","ref":"@e1"} or {"action":"drag","from":"@e1","to":"@e2"}.\n'
        f"Task: {task_desc}\n"
        f"Vision clues: {clues[:800]}\n"
        "Elements:\n" + "\n".join(el_lines)
    )
    model = os.getenv("KILO_REASONING_MODEL", os.getenv("KILO_DEFAULT_MODEL", "kilo/kilo/auto-free"))
    kilo = KiloWrapper(backend=Backend.CLI, model=model)
    resp = kilo.complete(prompt, model=model, max_tokens=220, temperature=0.0)
    data = _extract_json_obj(resp.content) or {}
    action = str(data.get("action", "")).strip()

    if action == "click" and data.get("ref"):
        browser.click(str(data["ref"]))
        return "kilo-cli:click"
    if action == "double_click" and data.get("ref"):
        browser.double_click(str(data["ref"]))
        return "kilo-cli:double_click"
    if action == "drag" and data.get("from") and data.get("to"):
        browser.drag(str(data["from"]), str(data["to"]))
        return "kilo-cli:drag"
    if action == "press" and data.get("key"):
        browser.press(str(data["key"]))
        return "kilo-cli:press"
    if action == "mouse_wheel":
        browser.mouse_wheel(int(data.get("dy", 300)), int(data.get("dx", 0)))
        return "kilo-cli:mouse_wheel"
    return None


def _split_csv(values: str) -> list[str]:
    return [v.strip() for v in (values or "").split(",") if v.strip()]


def _build_reasoning_client(config: Any) -> FallbackLLMClient | None:
    if hasattr(config, "get_browser_text_offer_chain"):
        aliases = config.get_browser_text_offer_chain()
        policy = config.get_error_policy() if hasattr(config, "get_error_policy") else None
    else:
        primary = getattr(config, "browser_reasoning_model", "") or getattr(config, "text_model_primary", "openrouter_primary")
        fallbacks = _split_csv(getattr(config, "text_model_fallbacks", "openrouter_trinity,kilo_glm5"))
        aliases = [primary] + fallbacks
        policy = None

    offers = resolve_offers(config, aliases, modality="text")
    return FallbackLLMClient(offers, error_policy=policy) if offers else None


def _build_vision_client(config: Any) -> FallbackLLMClient | None:
    if hasattr(config, "get_browser_vision_offer_chain"):
        aliases = config.get_browser_vision_offer_chain()
        policy = config.get_error_policy() if hasattr(config, "get_error_policy") else None
    else:
        primary = getattr(config, "browser_vision_model", "") or getattr(config, "vision_model_primary", "openrouter_vision_primary")
        fallbacks = _split_csv(getattr(config, "vision_model_fallbacks", "openrouter_nemotron_vl"))
        kilo_model = getattr(config, "kilo_browser_vision_model", "")
        if kilo_model:
            fallbacks.append(kilo_model)
        aliases = [primary] + fallbacks
        policy = None

    offers = resolve_offers(config, aliases, modality="vision")
    return FallbackLLMClient(offers, error_policy=policy) if offers else None


def _simple_navigate_or_search(browser: AgentBrowser, task_desc: str) -> str:
    url = _extract_url(task_desc)
    if url:
        browser.open(url)
        browser.wait(1500)
        return url

    browser.open("https://duckduckgo.com")
    query = task_desc.strip()[:300]
    js = (
        "const el = document.querySelector('input[name=\"q\"]');"
        "if (el) { el.value = " + json.dumps(query) + "; el.form.submit(); 'submitted'; }"
        "else { 'search input not found'; }"
    )
    browser.eval_js(js)
    browser.wait(2000)
    return "https://duckduckgo.com"


def _attempt_captcha_once(
    browser: AgentBrowser,
    task_desc: str,
    snapshot: dict[str, Any],
    reasoning_client: FallbackLLMClient | None,
    vision_client: FallbackLLMClient | None,
    run_dir: Path | None,
) -> tuple[bool, str]:
    clues = ""
    if vision_client and run_dir:
        shot_path = str(run_dir / "captcha_before.png")
        try:
            browser.screenshot(shot_path, full_page=True)
            # Use screenshot description helper via base64 expected format.
            import base64

            image_b64 = base64.b64encode(Path(shot_path).read_bytes()).decode("ascii")
            clues = describe_screenshot(vision_client, image_b64, task_desc, "captcha-detected")
            (run_dir / "captcha_vision.txt").write_text(clues)
        except Exception as e:
            logger.warning(f"Captcha vision assist failed: {e}")

    # Let reasoning model propose one action first (helps with non-checkbox and drag puzzles).
    if reasoning_client:
        try:
            llm_note = _run_llm_captcha_action(browser, reasoning_client, task_desc, snapshot, clues)
            if llm_note:
                browser.wait(1500)
                return True, llm_note
        except Exception as e:
            logger.warning(f"Captcha reasoning action failed: {e}")
            try:
                kilo_note = _run_kilo_cli_captcha_action(browser, task_desc, snapshot, clues)
                if kilo_note:
                    browser.wait(1500)
                    return True, kilo_note
            except Exception as kilo_e:
                logger.warning(f"KILO CLI captcha action failed: {kilo_e}")

    # Heuristic fallback: click likely checkbox/button challenge controls.
    keywords = [
        "i am not a robot",
        "not a robot",
        "verify",
        "continue",
        "start",
        "checkbox",
    ]

    for keyword in keywords:
        el = find_element_by(snapshot, name_contains=keyword)
        if el and el.get("ref"):
            try:
                browser.click(el["ref"])
                browser.wait(1500)
                return True, f"clicked:{keyword}"
            except Exception as e:
                logger.debug(f"Captcha click failed for {keyword}: {e}")

    # Second chance with minimal JS for checkbox-based captchas in same-origin contexts.
    try:
        js_result = browser.eval_js(
            "const cb = document.querySelector('input[type=checkbox]');"
            "if (cb) { cb.click(); 'checkbox-clicked'; } else { 'no-checkbox'; }"
        )
        if "clicked" in (js_result or ""):
            browser.wait(1200)
            return True, "js-checkbox"
    except Exception:
        pass

    if clues:
        return False, "no-actionable-control-from-vision"
    return False, "no-actionable-control"


def run_browser_task(
    config: Any,
    task_desc: str,
    mode: str | None = None,
    max_steps: int | None = None,
    capture_artifacts: bool = True,
) -> str:
    """Run a browser task through AgentBrowser and return a JSON summary string."""
    backend = mode or getattr(config, "browser_mode", "hybrid")
    run_dir = _get_run_dir(config, capture_artifacts)
    result: dict[str, Any] = {
        "backend": "agent_browser",
        "requested_mode": backend,
        "attempts": 0,
        "solved": False,
        "blocked_reason": None,
        "url": None,
        "title": None,
        "artifact_dir": str(run_dir) if run_dir else None,
        "max_steps": max_steps,
    }

    logger.info(
        "browser_task_start backend=agent_browser mode=%s capture_artifacts=%s",
        backend,
        bool(run_dir),
    )

    vision_client = _build_vision_client(config)
    reasoning_client = _build_reasoning_client(config)

    browser: AgentBrowser | None = None
    try:
        headed = bool(getattr(config, "browser_headed", False))
        browser = AgentBrowser(StealthConfig(headed=headed))
        browser.start()

        target = _simple_navigate_or_search(browser, task_desc)
        snapshot = browser.snapshot(interactive=True)
        page_text = _clean_js_value(browser.get_text()) or ""
        title = _clean_js_value(browser.get_title())
        url = _clean_js_value(browser.get_url()) or target
        blockers = detect_browser_blockers(page_text, "")

        result["url"] = url
        result["title"] = title
        result["text_preview"] = page_text[:280]
        result["attempts"] = 1
        result["signals"] = blockers

        if run_dir:
            (run_dir / "summary_pre.json").write_text(json.dumps(result, indent=2))
            (run_dir / "page_text.txt").write_text(page_text)
            try:
                browser.screenshot(str(run_dir / "page.png"), full_page=True)
            except Exception:
                pass

        if blockers["is_captcha"]:
            allowed_attempts = int(getattr(config, "captcha_auto_attempts", 1))
            if allowed_attempts > 0:
                solved, attempt_note = _attempt_captcha_once(
                    browser,
                    task_desc,
                    snapshot,
                    reasoning_client,
                    vision_client,
                    run_dir,
                )
                result["captcha_attempt"] = attempt_note
                page_text_after = _clean_js_value(browser.get_text()) or ""
                blockers_after = detect_browser_blockers(page_text_after, "")
                result["signals_after"] = blockers_after
                if solved and not blockers_after["is_captcha"]:
                    result["solved"] = True
                else:
                    result["blocked_reason"] = "captcha_unsolved_after_single_attempt"
                    if run_dir:
                        try:
                            browser.screenshot(str(run_dir / "captcha_after.png"), full_page=True)
                        except Exception:
                            pass
            else:
                result["blocked_reason"] = "captcha_detected_no_attempt_allowed"
        else:
            result["solved"] = True

        if not result["solved"] and not result["blocked_reason"]:
            result["blocked_reason"] = "fallback_browser_incomplete"

        if run_dir:
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))

        logger.info(
            "browser_task_done solved=%s blocked_reason=%s url=%s",
            result["solved"],
            result["blocked_reason"],
            result["url"],
        )
        return json.dumps(result)

    except Exception as e:
        result["blocked_reason"] = f"browser_task_error:{type(e).__name__}"
        result["error"] = str(e)
        if run_dir:
            (run_dir / "error.txt").write_text(str(e))
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))
        logger.error("browser_task_failed: %s", e)
        return json.dumps(result)
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
