import time
import json
import logging
from pathlib import Path
from macgent.models import Action
from macgent.actions import safari_actions, mouse, calendar_actions
from macgent.perception.safari import run_osascript, execute_js_in_safari

logger = logging.getLogger("macgent.dispatcher")

# Config reference — set by the role before spawning an Agent
_dispatch_config = {"notion_token": "", "notion_database_id": "", "souls_dir": ""}


def set_dispatch_config(config):
    """Set config for dispatcher actions (Notion token, database ID, souls dir)."""
    _dispatch_config["notion_token"] = getattr(config, "notion_token", "")
    _dispatch_config["notion_database_id"] = getattr(config, "notion_database_id", "")
    _dispatch_config["souls_dir"] = getattr(config, "souls_dir", "")


def _get_souls_dir() -> Path:
    """Get souls directory from config or default."""
    sd = _dispatch_config.get("souls_dir", "")
    if sd:
        return Path(sd)
    return Path(__file__).parent.parent.parent / "souls"


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

        elif t == "read_skill":
            souls_dir = _get_souls_dir()
            skills_dir = souls_dir / "skills"
            name = p.get("name", "")
            path = skills_dir / f"{name}.md"
            if path.exists():
                return path.read_text()
            available = [f.stem for f in sorted(skills_dir.glob("*.md")) if f.stem != "README"]
            return f"Skill '{name}' not found. Available: {', '.join(available)}"

        elif t == "write_skill":
            souls_dir = _get_souls_dir()
            name = p.get("name", "")
            content = p.get("content", "")
            if not name or not content:
                return "ERROR: write_skill needs 'name' and 'content'"
            path = souls_dir / "skills" / f"{name}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"Skill '{name}' written to {path}"

        elif t == "write_identity":
            souls_dir = _get_souls_dir()
            role = p.get("role", "manager")
            content = p.get("content", "")
            if not content:
                return "ERROR: write_identity needs 'content'"
            path = souls_dir / role / "IDENTITY.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"Identity written for {role}"

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
