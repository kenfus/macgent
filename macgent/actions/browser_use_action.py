"""browser-use integration — delegates web browsing tasks to a Playwright-based agent.

Uses browser-use's own ChatOpenAI (no LangChain needed), pointed at whatever
OpenAI-compatible endpoint macgent is configured with (OpenRouter, Anthropic, etc.).
"""

import asyncio
import logging

logger = logging.getLogger("macgent.browser_use")


def _make_llm(config):
    """Build a browser-use LLM client from macgent config."""
    from browser_use.llm.openai.chat import ChatOpenAI
    return ChatOpenAI(
        model=config.reasoning_model,
        api_key=config.reasoning_api_key,
        base_url=config.reasoning_api_base,
        temperature=0.0,
        # Free/OpenRouter models often don't support forced JSON schema —
        # fall back to putting the schema in the system prompt instead.
        dont_force_structured_output=True,
        add_schema_to_system_prompt=True,
        max_completion_tokens=4096,
    )


def _find_chromium_path() -> str | None:
    """Find the playwright-installed headless shell or Chromium executable.

    Prefers chrome-headless-shell (a plain binary that works when launched directly
    as a subprocess) over the full Chromium .app bundle (which can have macOS launch
    issues when not started via Playwright's own mechanism).
    """
    import glob
    import pathlib
    pw_cache = pathlib.Path.home() / "Library/Caches/ms-playwright"

    # 1. Prefer chrome-headless-shell — plain binary, starts fast, no .app bundle issues
    shell_matches = sorted(glob.glob(str(pw_cache / "chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell")))
    if shell_matches:
        return shell_matches[-1]

    # 2. Fall back to full Chromium .app (ARM64)
    chromium_matches = sorted(glob.glob(str(pw_cache / "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))
    if chromium_matches:
        return chromium_matches[-1]

    return None


async def _run_task(config, task: str) -> str:
    """Run a browser task with browser-use and return the result as a string."""
    from browser_use import Agent
    from browser_use.browser import BrowserProfile, BrowserSession

    llm = _make_llm(config)

    chromium_path = _find_chromium_path()
    if chromium_path:
        logger.info(f"Using Chromium at: {chromium_path}")
    else:
        logger.warning("Chromium not found — browser-use will try to install it")

    profile = BrowserProfile(
        headless=True,
        executable_path=chromium_path,
    )
    session = BrowserSession(browser_profile=profile)

    agent = Agent(task=task, llm=llm, browser_session=session)
    try:
        history = await agent.run()
        # Extract final result from the agent's history
        result = history.final_result()
        if result:
            return str(result)
        # Fallback: last action's extracted content
        last = history.last_action()
        return str(last) if last else "(browser task completed, no text result)"
    finally:
        try:
            await session.close()
        except Exception:
            pass


def run_browser_task(config, task: str) -> str:
    """Synchronous entry point — runs the async browser-use agent in a new event loop."""
    try:
        return asyncio.run(_run_task(config, task))
    except Exception as e:
        logger.error(f"browser_task failed: {e}")
        return f"ERROR: browser_task failed: {e}"
