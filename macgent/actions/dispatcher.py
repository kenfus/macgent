import time
import json
import logging
import base64
from pathlib import Path
from macgent.models import Action
from macgent.actions import mouse, keyboard, calendar_actions
from macgent.actions.brave_search import brave_web_search_json
from macgent.utils_osascript import run_osascript
from macgent.reasoning.llm_client import build_vision_fallback_client

logger = logging.getLogger("macgent.dispatcher")

# Config reference — set by the role before spawning an Agent
_dispatch_config = {"workspace_dir": "", "_last_ceo_message": "", "_last_ceo_attachments": []}

# Core skills are shipped inside the package (browser, macos, communication) — fixed
_CORE_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def set_last_ceo_message(text: str, attachments: list[dict] | None = None) -> None:
    """Store the last injected CEO message so re_queue_message can refer to it without params."""
    _dispatch_config["_last_ceo_message"] = text
    _dispatch_config["_last_ceo_attachments"] = list(attachments or [])


def set_dispatch_config(config):
    """Set config for dispatcher actions (workspace dir, LLM)."""
    _dispatch_config["workspace_dir"] = getattr(config, "workspace_dir", "")
    _dispatch_config["reasoning_model"] = getattr(config, "reasoning_model", "")
    _dispatch_config["reasoning_api_key"] = getattr(config, "reasoning_api_key", "")
    _dispatch_config["reasoning_api_base"] = getattr(config, "reasoning_api_base", "")
    _dispatch_config["reasoning_api_type"] = getattr(config, "reasoning_api_type", "openai")
    _dispatch_config["vision_api_key"] = getattr(config, "vision_api_key", "")
    _dispatch_config["vision_api_base"] = getattr(config, "vision_api_base", "")
    _dispatch_config["vision_api_type"] = getattr(config, "vision_api_type", "openai")
    _dispatch_config["browser_mode"] = getattr(config, "browser_mode", "agent_browser")
    _dispatch_config["browser_fallback_threshold"] = getattr(config, "browser_fallback_threshold", 3)
    _dispatch_config["captcha_auto_attempts"] = getattr(config, "captcha_auto_attempts", 1)
    _dispatch_config["browser_reasoning_model"] = getattr(config, "browser_reasoning_model", "")
    _dispatch_config["browser_vision_model"] = getattr(config, "browser_vision_model", "")
    _dispatch_config["browser_headed"] = getattr(config, "browser_headed", False)
    _dispatch_config["text_model_primary"] = getattr(config, "text_model_primary", "")
    _dispatch_config["text_model_fallbacks"] = getattr(config, "text_model_fallbacks", "")
    _dispatch_config["vision_model_primary"] = getattr(config, "vision_model_primary", "")
    _dispatch_config["vision_model_fallbacks"] = getattr(config, "vision_model_fallbacks", "")
    _dispatch_config["vision_model"] = getattr(config, "vision_model", "")
    _dispatch_config["model_config"] = getattr(config, "model_config", {})
    _dispatch_config["error_policy"] = getattr(config, "get_error_policy", lambda: {})()
    _dispatch_config["kilo_browser_vision_model"] = getattr(config, "kilo_browser_vision_model", "")
    _dispatch_config["kilo_api_key"] = getattr(config, "kilo_api_key", "")
    _dispatch_config["kilo_api_base"] = getattr(config, "kilo_api_base", "")
    _dispatch_config["brave_search_api_key"] = getattr(config, "brave_search_api_key", "")
    _dispatch_config["brave_search_api_base"] = getattr(config, "brave_search_api_base", "https://api.search.brave.com")


def _get_workspace_dir() -> Path:
    """Get workspace directory from config or default."""
    wd = _dispatch_config.get("workspace_dir", "")
    if wd:
        return Path(wd)
    return Path(__file__).parent.parent.parent / "workspace"


def _read_image_as_base64(path_or_rel: str) -> str:
    path = Path(path_or_rel)
    if not path.is_absolute():
        path = (_get_workspace_dir() / path_or_rel).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path_or_rel}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _resolve_workspace_path(path_or_rel: str) -> Path:
    """Resolve relative or absolute path and enforce workspace sandbox."""
    workspace = _get_workspace_dir().resolve()
    raw = Path(path_or_rel)
    path = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    if not str(path).startswith(str(workspace)):
        raise ValueError("path must be within workspace")
    return path


def _build_dispatch_vision_client():
    class _VisionCfg:
        reasoning_api_base = _dispatch_config.get("reasoning_api_base", "https://openrouter.ai/api/v1")
        reasoning_api_key = _dispatch_config.get("reasoning_api_key", "")
        reasoning_api_type = _dispatch_config.get("reasoning_api_type", "openai")
        reasoning_model = _dispatch_config.get("reasoning_model", "")
        vision_api_base = _dispatch_config.get("vision_api_base", "https://openrouter.ai/api/v1")
        vision_api_key = _dispatch_config.get("vision_api_key", "")
        vision_api_type = _dispatch_config.get("vision_api_type", "openai")
        vision_model = _dispatch_config.get("vision_model", "")
        kilo_api_base = _dispatch_config.get("kilo_api_base", "https://api.kilo.ai/v1")
        kilo_api_key = _dispatch_config.get("kilo_api_key", "")

        @staticmethod
        def get_vision_offer_chain():
            primary = _dispatch_config.get("vision_model_primary", "")
            fallbacks = [x.strip() for x in _dispatch_config.get("vision_model_fallbacks", "").split(",") if x.strip()]
            return [x for x in [primary, *fallbacks] if x]

        @staticmethod
        def get_error_policy():
            return _dispatch_config.get("error_policy", {})

        @staticmethod
        def get_offer_definition(alias: str, modality: str):
            return _dispatch_config.get("model_config", {}).get("offers", {}).get(modality, {}).get(alias)

        @staticmethod
        def get_provider_definition(provider: str):
            return _dispatch_config.get("model_config", {}).get("providers", {}).get(provider)

    return build_vision_fallback_client(_VisionCfg())


def dispatch(action: Action) -> str:
    """Execute an action and return result string."""
    t = action.type
    p = action.params

    try:
        if t == "applescript":
            script = p.get("script", "")
            if not script:
                return "ERROR: applescript needs 'script'"
            timeout = int(p.get("timeout", 15))
            return run_osascript(script, timeout=timeout) or "(no output)"

        elif t == "mouse_click":
            return mouse.mouse_click(int(p["x"]), int(p["y"]))

        elif t == "mouse_double_click":
            return mouse.mouse_double_click(int(p["x"]), int(p["y"]))

        elif t == "mouse_move":
            return mouse.mouse_move(int(p["x"]), int(p["y"]))

        elif t == "key_press":
            key = p.get("key", "")
            if not key:
                return "ERROR: key_press needs 'key'"
            return keyboard.key_press(key)

        elif t == "type_string":
            text = p.get("text", "")
            if text == "":
                return "ERROR: type_string needs 'text'"
            return keyboard.type_string(text)

        elif t == "screenshot":
            from datetime import datetime
            path = p.get("path", "")
            if not path:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                path = f"screenshots/{ts}.png"
            try:
                full_path = _resolve_workspace_path(path)
            except ValueError:
                return "ERROR: path must be within workspace"
            full_path.parent.mkdir(parents=True, exist_ok=True)
            mouse.take_screenshot(str(full_path))
            return f"Screenshot saved: {path}"

        elif t == "screenshot_grid":
            # Take a screenshot of a region and burn an absolute-coordinate grid onto it.
            # Read the coordinate labels in the image to know exactly where to click.
            from datetime import datetime
            path = p.get("path", "")
            if not path:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                path = f"screenshots/grid_{ts}.png"
            try:
                full_path = _resolve_workspace_path(path)
            except ValueError:
                return "ERROR: path must be within workspace"
            full_path.parent.mkdir(parents=True, exist_ok=True)
            mouse.take_annotated_screenshot(
                str(full_path),
                x=int(p.get("x", 0)),
                y=int(p.get("y", 0)),
                w=int(p.get("w", 0)),
                h=int(p.get("h", 0)),
                grid_step=int(p.get("grid_step", 35)),
            )
            return (
                f"[screenshot_grid] Annotated screenshot saved: {path} "
                f"(grid_step={p.get('grid_step', 35)}px, origin=({p.get('x', 0)},{p.get('y', 0)}))\n"
                f"Use this path in evaluate_image: {path}"
            )

        elif t == "locate_in_app":
            import re
            app = p.get("app", "")
            query = p.get("query", "")
            if not app or not query:
                return "ERROR: locate_in_app needs 'app' and 'query'"
            grid_step = int(p.get("grid_step", 50))

            # 1. Get window bounds
            bounds_script = (
                f'tell application "System Events"\n'
                f'  tell process "{app}"\n'
                f'    set pos to position of window 1\n'
                f'    set sz to size of window 1\n'
                f'    return (item 1 of pos) & "," & (item 2 of pos) & "," & (item 1 of sz) & "," & (item 2 of sz)\n'
                f'  end tell\n'
                f'end tell'
            )
            bounds_raw = run_osascript(bounds_script, timeout=10) or ""
            nums = [int(s.strip()) for s in re.split(r'[,\s]+', bounds_raw) if s.strip().lstrip("-").isdigit()]
            if len(nums) < 4:
                return f"ERROR: Could not get window bounds for '{app}': {bounds_raw}"
            win_x, win_y, win_w, win_h = nums[0], nums[1], nums[2], nums[3]

            # 2. Gridded screenshot
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            rel_path = f"screenshots/locate_{ts}.png"
            full_path = _resolve_workspace_path(rel_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            mouse.take_annotated_screenshot(str(full_path), x=win_x, y=win_y, w=win_w, h=win_h, grid_step=grid_step)

            # 3. Ask vision model to read the grid labels and return absolute coords
            image_b64 = base64.b64encode(full_path.read_bytes()).decode("ascii")
            prompt = (
                f"This image has a red coordinate grid burned onto it. "
                f"Every grid line is labeled with its ABSOLUTE screen coordinate. "
                f"Find: {query}. "
                f"Read the grid labels nearest the element's center and return its absolute coordinates. "
                f"Reply with ONLY: x=<number>, y=<number>"
            )
            client = _build_dispatch_vision_client()
            raw = client.chat_with_image(prompt=prompt, image_base64=image_b64, max_tokens=80)

            # 4. Parse x=N, y=N from response
            m = re.search(r'x\s*[=:]\s*(\d+).*?y\s*[=:]\s*(\d+)', raw, re.IGNORECASE | re.DOTALL)
            if m:
                abs_x, abs_y = int(m.group(1)), int(m.group(2))
                return json.dumps({"x": abs_x, "y": abs_y, "screenshot": rel_path})
            return json.dumps({"x": None, "y": None, "screenshot": rel_path, "raw": raw})

        elif t == "open_app":
            app = p["app"]
            run_osascript(f'tell application "{app}" to activate')
            time.sleep(1)
            return f"Opened {app}"

        elif t == "calendar_add":
            return calendar_actions.add_event(
                summary=p["summary"],
                year=int(p["year"]),
                month=int(p["month"]),
                day=int(p["day"]),
                hour=int(p.get("hour", 12)),
                minute=int(p.get("minute", 0)),
                duration_hours=int(p.get("duration_hours", 1)),
                calendar_name=p.get("calendar"),
            )

        elif t == "calendar_read":
            return calendar_actions.read_events(
                year=int(p["year"]),
                month=int(p["month"]),
                day=int(p["day"]),
            )

        elif t == "imessage_read":
            from macgent.actions import imessage_actions
            return imessage_actions.read_messages(
                contact=p.get("contact", ""),
                limit=int(p.get("limit", 10)),
            )

        elif t == "imessage_send":
            from macgent.actions import imessage_actions
            return imessage_actions.send_message(
                contact=p["contact"],
                text=p["text"],
            )

        elif t == "mail_read":
            from macgent.actions import mail_actions
            return mail_actions.read_inbox(limit=int(p.get("limit", 5)))

        elif t == "mail_read_message":
            from macgent.actions import mail_actions
            return mail_actions.read_email(message_number=int(p.get("number", 1)))

        elif t == "mail_send":
            from macgent.actions import mail_actions
            return mail_actions.send_email(
                to=p["to"],
                subject=p["subject"],
                body=p["body"],
            )

        elif t == "mail_reply":
            from macgent.actions import mail_actions
            return mail_actions.reply_email(
                message_number=int(p["number"]),
                body=p["body"],
            )

        elif t == "brave_search":
            query = p.get("query", "").strip()
            if not query:
                return "ERROR: brave_search needs 'query'"
            return brave_web_search_json(
                api_key=_dispatch_config.get("brave_search_api_key", ""),
                api_base=_dispatch_config.get("brave_search_api_base", "https://api.search.brave.com"),
                query=query,
                count=int(p.get("count", 5)),
                country=p.get("country"),
                search_lang=p.get("search_lang"),
                safesearch=p.get("safesearch", "moderate"),
                freshness=p.get("freshness"),
            )

        elif t == "evaluate_image":
            # Use vision chain even when reasoning model itself is text-only.
            image_b64 = p.get("image_base64", "")
            image_path = p.get("path", "")
            prompt = p.get("prompt", "Describe this image and list key actionable details.")
            media_type = p.get("media_type", "image/png")
            if not image_b64:
                if not image_path:
                    return "ERROR: evaluate_image needs 'path' or 'image_base64'"
                image_b64 = _read_image_as_base64(image_path)
            client = _build_dispatch_vision_client()
            result = client.chat_with_image(
                prompt=prompt,
                image_base64=image_b64,
                image_media_type=media_type,
                max_tokens=int(p.get("max_tokens", 800)),
            )
            return result

        elif t == "read_file":
            # Read a file in the workspace. Optional offset/limit for line ranges.
            rel = p.get("path", "")
            if not rel:
                return "ERROR: read_file needs 'path'"
            try:
                path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            if not path.exists():
                return f"File not found: {rel}"
            lines = path.read_text().splitlines(keepends=True)
            offset = int(p["offset"]) - 1 if "offset" in p else 0  # 1-indexed → 0-indexed
            limit = int(p["limit"]) if "limit" in p else len(lines)
            chunk = lines[offset:offset + limit]
            # Return with line numbers (like cat -n), so edit_file references are clear
            numbered = "".join(f"{offset + i + 1:4d}  {line}" for i, line in enumerate(chunk))
            return numbered or "(empty)"

        elif t == "write_file":
            # Write (overwrite) a file in the workspace.
            rel = p.get("path", "")
            content = p.get("content", "")
            if not rel:
                return "ERROR: write_file needs 'path' and 'content'"
            try:
                path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            logger.info(f"File written: {rel} ({len(content)} chars)")
            return f"Written: {rel}"

        elif t == "append_file":
            # Append content to a file in the workspace. Creates file if missing.
            rel = p.get("path", "")
            content = p.get("content", "")
            if not rel:
                return "ERROR: append_file needs 'path' and 'content'"
            try:
                path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"File appended: {rel} (+{len(content)} chars)")
            return f"Appended: {rel}"

        elif t == "append_to_daily_memory":
            # Append cleaned text to <workspace>/memory/<YYYY-MM-DD>_MEMORY.md.
            text = p.get("text", p.get("content", ""))
            if not str(text).strip():
                return "ERROR: append_to_daily_memory needs non-empty 'text' (or 'content')"

            from macgent.memory import MemoryManager

            class _Cfg:
                workspace_dir = str(_get_workspace_dir())

            mm = MemoryManager(_Cfg())
            written_path = mm.append_to_daily_memory(str(text))
            return f"Appended daily memory: {written_path}"

        elif t == "edit_file":
            # Replace exact text in a file — like a precise find-and-replace.
            # old_string must match exactly (including whitespace/indentation).
            rel = p.get("path", "")
            old = p.get("old_string", "")
            new = p.get("new_string", "")
            if not rel or old == "":
                return "ERROR: edit_file needs 'path', 'old_string', and 'new_string'"
            try:
                path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            if not path.exists():
                return f"File not found: {rel}"
            content = path.read_text()
            if old not in content:
                return f"ERROR: old_string not found in {rel}"
            if content.count(old) > 1:
                return f"ERROR: old_string matches {content.count(old)} places — make it more specific"
            path.write_text(content.replace(old, new, 1))
            logger.info(f"File edited: {rel}")
            return f"Edited: {rel}"

        elif t == "delete_file":
            # Delete a file in the workspace.
            rel = p.get("path", "")
            if not rel:
                return "ERROR: delete_file needs 'path'"
            try:
                path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            if not path.exists():
                return f"File not found: {rel}"
            path.unlink()
            logger.info(f"File deleted: {rel}")
            return f"Deleted: {rel}"

        elif t == "browser_task":
            # Delegate a full browsing task to browser-use (Playwright-based).
            # The agent handles navigation, clicks, and extraction internally.
            task_desc = p.get("task", p.get("description", ""))
            if not task_desc:
                return "ERROR: browser_task needs 'task'"
            try:
                from macgent.actions.browser_use_action import run_browser_task

                class _Cfg:
                    reasoning_model = _dispatch_config.get("reasoning_model", "")
                    reasoning_api_key = _dispatch_config.get("reasoning_api_key", "")
                    reasoning_api_base = _dispatch_config.get("reasoning_api_base", "")
                    reasoning_api_type = _dispatch_config.get("reasoning_api_type", "openai")
                    vision_api_key = _dispatch_config.get("vision_api_key", "")
                    vision_api_base = _dispatch_config.get("vision_api_base", "")
                    vision_api_type = _dispatch_config.get("vision_api_type", "openai")
                    workspace_dir = str(_get_workspace_dir())
                    browser_mode = _dispatch_config.get("browser_mode", "agent_browser")
                    browser_fallback_threshold = int(_dispatch_config.get("browser_fallback_threshold", 3))
                    captcha_auto_attempts = int(_dispatch_config.get("captcha_auto_attempts", 1))
                    browser_reasoning_model = _dispatch_config.get("browser_reasoning_model", _dispatch_config.get("reasoning_model", ""))
                    browser_vision_model = _dispatch_config.get("browser_vision_model", _dispatch_config.get("vision_model", ""))
                    browser_headed = bool(_dispatch_config.get("browser_headed", False))
                    text_model_primary = _dispatch_config.get("text_model_primary", "")
                    text_model_fallbacks = _dispatch_config.get("text_model_fallbacks", "")
                    vision_model_primary = _dispatch_config.get("vision_model_primary", "")
                    vision_model_fallbacks = _dispatch_config.get("vision_model_fallbacks", "")
                    vision_model = _dispatch_config.get("browser_vision_model", _dispatch_config.get("vision_model", ""))
                    model_config = _dispatch_config.get("model_config", {})
                    kilo_api_base = _dispatch_config.get("kilo_api_base", "")
                    kilo_api_key = _dispatch_config.get("kilo_api_key", "")
                    kilo_browser_vision_model = _dispatch_config.get("kilo_browser_vision_model", "")

                    @staticmethod
                    def get_error_policy():
                        return _dispatch_config.get("error_policy", {})

                    @staticmethod
                    def get_offer_definition(alias: str, modality: str):
                        return _dispatch_config.get("model_config", {}).get("offers", {}).get(modality, {}).get(alias)

                    @staticmethod
                    def get_provider_definition(provider: str):
                        return _dispatch_config.get("model_config", {}).get("providers", {}).get(provider)

                    @staticmethod
                    def get_browser_text_offer_chain():
                        primary = _dispatch_config.get("browser_reasoning_model") or _dispatch_config.get("text_model_primary", "")
                        fallbacks = [x.strip() for x in _dispatch_config.get("text_model_fallbacks", "").split(",") if x.strip()]
                        return [x for x in [primary, *fallbacks] if x]

                    @staticmethod
                    def get_browser_vision_offer_chain():
                        primary = _dispatch_config.get("browser_vision_model") or _dispatch_config.get("vision_model_primary", "")
                        fallbacks = [x.strip() for x in _dispatch_config.get("vision_model_fallbacks", "").split(",") if x.strip()]
                        kilo_model = _dispatch_config.get("kilo_browser_vision_model", "")
                        if kilo_model:
                            fallbacks.append(kilo_model)
                        return [x for x in [primary, *fallbacks] if x]

                return run_browser_task(
                    _Cfg(),
                    task_desc,
                    mode=p.get("mode"),
                    max_steps=p.get("max_steps"),
                    capture_artifacts=bool(p.get("capture_artifacts", True)),
                )
            except Exception as e:
                return f"ERROR: browser_task: {e}"

        elif t == "http_request":
            # Make an HTTP request to any URL and return the response body.
            # Retries on 429/503/504 with exponential backoff (uses error_policy config).
            import urllib.request
            import urllib.error
            method = p.get("method", "GET").upper()
            url = p.get("url", "")
            headers = p.get("headers", {})
            body = p.get("body", None)
            timeout = int(p.get("timeout", 15))
            if not url:
                return "ERROR: http_request needs 'url'"
            body_bytes = None
            if body is not None:
                if isinstance(body, dict):
                    body_bytes = json.dumps(body).encode()
                    headers.setdefault("Content-Type", "application/json")
                else:
                    body_bytes = str(body).encode()

            policy = _dispatch_config.get("error_policy", {})
            retry_statuses = set(int(x) for x in policy.get("retry_statuses", [429, 503, 504]))
            max_retries = int(policy.get("max_retries_per_offer", 3))
            backoff = float(policy.get("backoff_seconds", 2.0))
            backoff_mult = float(policy.get("backoff_multiplier", 2.0))

            last_error = ""
            for attempt in range(1, max_retries + 2):  # +1 for initial attempt
                req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        status = resp.status
                        raw = resp.read().decode(errors="replace")
                        return f"HTTP {status}\n{raw}"
                except urllib.error.HTTPError as e:
                    if e.code in retry_statuses and attempt <= max_retries:
                        logger.info("http_request status=%d, retrying in %.1fs (attempt %d/%d)", e.code, backoff, attempt, max_retries)
                        time.sleep(backoff)
                        backoff *= backoff_mult
                        continue
                    raw = e.read().decode(errors="replace")
                    return f"HTTP {e.code} {e.reason}\n{raw}"
                except urllib.error.URLError as e:
                    return f"ERROR: http_request failed: {e.reason}"
            return last_error or "ERROR: http_request failed after retries"

        elif t == "execute_script":
            # Execute inline Python code directly — no file needed.
            import subprocess, tempfile, os, textwrap
            code = p.get("code", "")
            if not code:
                return "ERROR: execute_script needs 'code'"
            extra_env = p.get("env", {})
            env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}
            timeout = int(p.get("timeout", 30))
            # Write to a temp file and run — cleaner than -c for multi-line code
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
                tf.write(textwrap.dedent(code))
                tmp_path = tf.name
            try:
                result = subprocess.run(
                    ["python3", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    cwd=str(_get_workspace_dir()),
                )
                out = result.stdout.strip()
                err = result.stderr.strip()
                parts = []
                if out:
                    parts.append(out)
                if err:
                    parts.append(f"[stderr]\n{err}")
                if result.returncode != 0:
                    parts.append(f"[exit {result.returncode}]")
                return "\n".join(parts) or "(no output)"
            except subprocess.TimeoutExpired:
                return f"ERROR: execute_script timed out after {timeout}s"
            finally:
                os.unlink(tmp_path)

        elif t == "run_script":
            # Execute a Python script file from the workspace via subprocess.
            # The agent writes the file first (write_file), then calls run_script.
            import subprocess
            rel = p.get("path", "")
            if not rel:
                return "ERROR: run_script needs 'path' (relative to workspace)"
            try:
                script_path = _resolve_workspace_path(rel)
            except ValueError:
                return "ERROR: path must be within workspace"
            if not script_path.exists():
                return f"ERROR: script not found: {rel}"
            args = p.get("args", [])
            extra_env = p.get("env", {})
            import os
            env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}
            timeout = int(p.get("timeout", 30))
            cmd = ["python3", str(script_path)] + [str(a) for a in args]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    cwd=str(_get_workspace_dir()),
                )
                out = result.stdout.strip()
                err = result.stderr.strip()
                parts = []
                if out:
                    parts.append(out)
                if err:
                    parts.append(f"[stderr]\n{err}")
                if result.returncode != 0:
                    parts.append(f"[exit {result.returncode}]")
                return "\n".join(parts) or "(no output)"
            except subprocess.TimeoutExpired:
                return f"ERROR: run_script timed out after {timeout}s"

        elif t == "run_shell":
            # Run a shell command in the persistent tmux session (macgent_shell).
            # State (cwd, env vars, processes) persists between calls.
            # Attach with: tmux attach -t macgent_shell
            from macgent.actions.shell_session import run as _shell_run
            command = p.get("command", "").strip()
            if not command:
                return "ERROR: run_shell needs 'command'"
            timeout = int(p.get("timeout", 60))
            return _shell_run(command, timeout=timeout)

        elif t == "wait":
            seconds = float(p.get("seconds", 2))
            time.sleep(seconds)
            return f"Waited {seconds}s"

        elif t == "re_queue_message":
            text = p.get("text", "").strip() or _dispatch_config.get("_last_ceo_message", "").strip()
            if not text:
                return "ERROR: re_queue_message — no pending CEO message to defer"
            attachments = _dispatch_config.get("_last_ceo_attachments", [])
            from macgent import message_bus
            message_bus.enqueue_message(
                "ceo",
                "agent",
                task_id=None,
                content=text,
                attachments=attachments,
            )
            message_bus.request_wake()
            _dispatch_config["_last_ceo_message"] = ""
            _dispatch_config["_last_ceo_attachments"] = []
            return "Message re-queued — will be handled after the current task."

        elif t == "done":
            return "TASK_COMPLETE"

        elif t == "fail":
            return "TASK_FAILED: " + p.get("reason", "unknown")

        else:
            return f"ERROR: Unknown action type '{t}'. Do not retry. Check your Skills context for supported actions and use the correct type."

    except Exception as e:
        logger.error(f"Action error: {e}")
        return f"ERROR: {type(e).__name__}: {e}"
