"""Thin agent-browser wrapper for dispatcher and CLI."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from macgent.actions.agent_browser import AgentBrowser, StealthConfig

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
    return match.group(0) if match else None


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


def run_browser_task(
    config: Any,
    task_desc: str,
    mode: str | None = None,
    max_steps: int | None = None,
    capture_artifacts: bool = True,
) -> str:
    """Open a task URL in agent-browser and return a structured JSON result."""
    requested_mode = mode or getattr(config, "browser_mode", "agent_browser")
    run_dir = _get_run_dir(config, capture_artifacts)

    result: dict[str, Any] = {
        "backend": "agent_browser",
        "requested_mode": requested_mode,
        "attempts": 0,
        "solved": False,
        "blocked_reason": None,
        "url": None,
        "title": None,
        "artifact_dir": str(run_dir) if run_dir else None,
        "max_steps": max_steps,
    }

    target_url = _extract_url(task_desc)
    if not target_url:
        result["blocked_reason"] = "no_url_in_task_desc"
        result["error"] = (
            "browser_task requires an explicit URL in task text. "
            "Use brave_search first for lookup tasks, then pass a URL."
        )
        if run_dir:
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))
        return json.dumps(result)

    browser: AgentBrowser | None = None
    try:
        headed = bool(getattr(config, "browser_headed", False))
        browser = AgentBrowser(StealthConfig(headed=headed))
        browser.start()
        browser.open(target_url)
        browser.wait(1500)

        result["attempts"] = 1
        result["url"] = _clean_js_value(browser.get_url()) or target_url
        result["title"] = _clean_js_value(browser.get_title())
        result["text_preview"] = (_clean_js_value(browser.get_text()) or "")[:280]
        result["solved"] = True

        if run_dir:
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))
            try:
                browser.screenshot(str(run_dir / "page.png"), full_page=True)
            except Exception:
                pass

        logger.info("browser_task_done solved=true url=%s", result["url"])
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
