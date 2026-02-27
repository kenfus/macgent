import time
import json
import logging
import base64
from pathlib import Path
from macgent.models import Action
from macgent.actions import safari_actions, mouse, calendar_actions
from macgent.perception.safari import execute_js_in_safari
from macgent.utils_osascript import run_osascript
from macgent.reasoning.llm_client import build_vision_fallback_client

logger = logging.getLogger("macgent.dispatcher")

# Config reference — set by the role before spawning an Agent
_dispatch_config = {"notion_token": "", "notion_database_id": "", "workspace_dir": ""}

# Core skills are shipped inside the package (browser, macos, communication) — fixed
_CORE_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def set_dispatch_config(config):
    """Set config for dispatcher actions (Notion token, database ID, workspace dir, LLM)."""
    _dispatch_config["notion_token"] = getattr(config, "notion_token", "")
    _dispatch_config["notion_database_id"] = getattr(config, "notion_database_id", "")
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
    _dispatch_config["text_model_primary"] = getattr(config, "text_model_primary", "openrouter_primary")
    _dispatch_config["text_model_fallbacks"] = getattr(config, "text_model_fallbacks", "openrouter_trinity,kilo_glm5")
    _dispatch_config["vision_model_primary"] = getattr(config, "vision_model_primary", "openrouter_vision_primary")
    _dispatch_config["vision_model_fallbacks"] = getattr(config, "vision_model_fallbacks", "openrouter_nemotron_vl")
    _dispatch_config["vision_model"] = getattr(config, "vision_model", "")
    _dispatch_config["model_config"] = getattr(config, "model_config", {})
    _dispatch_config["error_policy"] = getattr(config, "get_error_policy", lambda: {})()
    _dispatch_config["kilo_browser_vision_model"] = getattr(config, "kilo_browser_vision_model", "")
    _dispatch_config["kilo_api_key"] = getattr(config, "kilo_api_key", "")
    _dispatch_config["kilo_api_base"] = getattr(config, "kilo_api_base", "")


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
            primary = _dispatch_config.get("vision_model_primary", "openrouter_vision_primary")
            fallbacks = [x.strip() for x in _dispatch_config.get("vision_model_fallbacks", "").split(",") if x.strip()]
            return [primary, *fallbacks]

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
        if t == "navigate":
            return safari_actions.navigate(p["url"])

        elif t == "go_back":
            return safari_actions.go_back()

        elif t == "go_forward":
            return safari_actions.go_forward()

        elif t == "click":
            if "index" in p:
                return safari_actions.click_element_by_index(int(p["index"]))
            elif "selector" in p:
                return safari_actions.click_element(p["selector"])
            elif "text" in p:
                return safari_actions.click_element_by_text(p["text"], p.get("tag", "*"))
            else:
                return "ERROR: click needs 'index', 'selector', or 'text'"

        elif t == "click_element":
            if "index" in p:
                return safari_actions.click_element_by_index(int(p["index"]))
            elif "selector" in p:
                return safari_actions.click_element(p["selector"])
            elif "text" in p:
                return safari_actions.click_element_by_text(p["text"], p.get("tag", "*"))
            else:
                return "ERROR: click_element needs 'index', 'selector', or 'text'"

        elif t == "type":
            if "index" in p:
                return safari_actions.type_text_by_index(int(p["index"]), p["text"])
            elif "selector" in p:
                return safari_actions.type_text(p["selector"], p["text"])
            else:
                return safari_actions.type_text_by_keystroke(p["text"])

        elif t == "type_text":
            if "index" in p:
                return safari_actions.type_text_by_index(int(p["index"]), p["text"])
            elif "selector" in p:
                return safari_actions.type_text(p["selector"], p["text"])
            else:
                return safari_actions.type_text_by_keystroke(p["text"])

        elif t == "select_option":
            return safari_actions.select_option_by_index(int(p["index"]), p["value"])

        elif t == "key_press":
            return safari_actions.press_key(p["key"], p.get("modifiers"))

        elif t == "mouse_click":
            return mouse.mouse_click(int(p["x"]), int(p["y"]))

        elif t == "scroll":
            return safari_actions.scroll_page(
                p.get("direction", "down"),
                int(p.get("amount", 500)),
            )

        elif t == "execute_js":
            return execute_js_in_safari(p["code"])

        elif t == "new_tab":
            return safari_actions.new_tab(p.get("url", ""))

        elif t == "close_tab":
            return safari_actions.close_tab()

        elif t == "switch_tab":
            return safari_actions.switch_tab(int(p["tab"]))

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

        elif t == "mail_read_full":
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
            path = (_get_workspace_dir() / rel).resolve()
            if not str(path).startswith(str(_get_workspace_dir().resolve())):
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
            path = (_get_workspace_dir() / rel).resolve()
            if not str(path).startswith(str(_get_workspace_dir().resolve())):
                return "ERROR: path must be within workspace"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            logger.info(f"File written: {rel} ({len(content)} chars)")
            return f"Written: {rel}"

        elif t == "edit_file":
            # Replace exact text in a file — like a precise find-and-replace.
            # old_string must match exactly (including whitespace/indentation).
            rel = p.get("path", "")
            old = p.get("old_string", "")
            new = p.get("new_string", "")
            if not rel or old == "":
                return "ERROR: edit_file needs 'path', 'old_string', and 'new_string'"
            path = (_get_workspace_dir() / rel).resolve()
            if not str(path).startswith(str(_get_workspace_dir().resolve())):
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
            path = (_get_workspace_dir() / rel).resolve()
            if not str(path).startswith(str(_get_workspace_dir().resolve())):
                return "ERROR: path must be within workspace"
            if not path.exists():
                return f"File not found: {rel}"
            path.unlink()
            logger.info(f"File deleted: {rel}")
            return f"Deleted: {rel}"

        # ── Notion (generic) ──

        elif t == "notion_query":
            from macgent.actions import notion_actions
            token = _dispatch_config["notion_token"]
            db_id = _dispatch_config["notion_database_id"]
            result = notion_actions.notion_query(
                token, db_id,
                filter=p.get("filter"),
                sorts=p.get("sorts"),
                page_size=int(p.get("page_size", 50)),
            )
            return json.dumps(result, default=str)

        elif t == "notion_get":
            from macgent.actions import notion_actions
            token = _dispatch_config["notion_token"]
            page_id = p.get("page_id", "")
            result = notion_actions.notion_get(token, page_id)
            return json.dumps(result, default=str) if result else "ERROR: Page not found"

        elif t == "notion_update":
            from macgent.actions import notion_actions
            token = _dispatch_config["notion_token"]
            page_id = p.get("page_id", "")
            properties = p.get("properties", {})
            if not page_id or not properties:
                return "ERROR: notion_update needs 'page_id' and 'properties'"
            ok = notion_actions.notion_update(token, page_id, properties)
            return "Notion page updated" if ok else "ERROR: Notion update failed"

        elif t == "notion_create":
            from macgent.actions import notion_actions
            token = _dispatch_config["notion_token"]
            db_id = _dispatch_config["notion_database_id"]
            properties = p.get("properties", {})
            if not properties:
                return "ERROR: notion_create needs 'properties'"
            page_id = notion_actions.notion_create(token, db_id, properties)
            return json.dumps({"page_id": page_id}) if page_id else "ERROR: Notion create failed"

        elif t == "notion_schema":
            from macgent.actions import notion_actions
            token = _dispatch_config["notion_token"]
            db_id = _dispatch_config["notion_database_id"]
            return notion_actions.notion_schema(token, db_id)

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
                    text_model_primary = _dispatch_config.get("text_model_primary", "openrouter_primary")
                    text_model_fallbacks = _dispatch_config.get("text_model_fallbacks", "openrouter_trinity,kilo_glm5")
                    vision_model_primary = _dispatch_config.get("vision_model_primary", "openrouter_vision_primary")
                    vision_model_fallbacks = _dispatch_config.get("vision_model_fallbacks", "openrouter_nemotron_vl")
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
                        primary = _dispatch_config.get("browser_reasoning_model") or _dispatch_config.get("text_model_primary", "openrouter_primary")
                        fallbacks = [x.strip() for x in _dispatch_config.get("text_model_fallbacks", "").split(",") if x.strip()]
                        return [primary, *fallbacks]

                    @staticmethod
                    def get_browser_vision_offer_chain():
                        primary = _dispatch_config.get("browser_vision_model") or _dispatch_config.get("vision_model_primary", "openrouter_vision_primary")
                        fallbacks = [x.strip() for x in _dispatch_config.get("vision_model_fallbacks", "").split(",") if x.strip()]
                        kilo_model = _dispatch_config.get("kilo_browser_vision_model", "")
                        if kilo_model:
                            fallbacks.append(kilo_model)
                        return [primary, *fallbacks]

                return run_browser_task(
                    _Cfg(),
                    task_desc,
                    mode=p.get("mode"),
                    max_steps=p.get("max_steps"),
                    capture_artifacts=bool(p.get("capture_artifacts", True)),
                )
            except Exception as e:
                return f"ERROR: browser_task: {e}"

        elif t == "wait":
            seconds = float(p.get("seconds", 2))
            time.sleep(seconds)
            return f"Waited {seconds}s"

        elif t == "done":
            return "TASK_COMPLETE"

        elif t == "fail":
            return "TASK_FAILED: " + p.get("reason", "unknown")

        else:
            return f"ERROR: Unknown action type: {t}"

    except Exception as e:
        logger.error(f"Action error: {e}")
        return f"ERROR: {type(e).__name__}: {e}"
