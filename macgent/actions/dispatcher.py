import time
import logging
from macgent.models import Action
from macgent.actions import safari_actions, mouse, calendar_actions
from macgent.perception.safari import run_osascript, execute_js_in_safari

logger = logging.getLogger("macgent.dispatcher")

# Notion context for the current task — set by WorkerRole before spawning Agent
_current_notion_context = {"token": "", "page_id": ""}


def set_notion_context(token: str, page_id: str):
    """Set Notion credentials for the worker agent's notion_update action."""
    _current_notion_context["token"] = token
    _current_notion_context["page_id"] = page_id


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
            from pathlib import Path
            import os
            souls_dir = Path(os.getenv("MACGENT_SOULS_DIR", "")) or Path(__file__).parent.parent.parent / "souls"
            skills_dir = souls_dir.parent / "skills"
            name = p.get("name", "")
            path = skills_dir / f"{name}.md"
            if path.exists():
                return path.read_text()
            available = [f.stem for f in sorted(skills_dir.glob("*.md")) if f.stem != "README"]
            return f"Skill '{name}' not found. Available: {', '.join(available)}"

        elif t == "notion_update":
            from macgent.actions import notion_actions
            token = _current_notion_context.get("token", "")
            page_id = _current_notion_context.get("page_id", "")
            if not token or not page_id:
                return "ERROR: No Notion context set for this task"
            status = p.get("status")
            note = p.get("note", "")
            ok = notion_actions.update_task(token, page_id, status=status, note=note or None)
            return "Notion card updated" if ok else "ERROR: Notion update failed"

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
