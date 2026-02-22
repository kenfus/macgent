import time
import logging
from macgent.models import Action
from macgent.actions import safari_actions, mouse, calendar_actions
from macgent.perception.safari import run_osascript, execute_js_in_safari

logger = logging.getLogger("macgent.dispatcher")


def dispatch(action: Action) -> str:
    """Execute an action and return result string."""
    t = action.type
    p = action.params

    try:
        if t == "navigate":
            return safari_actions.navigate(p["url"])

        elif t == "execute_js":
            return execute_js_in_safari(p["code"])

        elif t == "click_element":
            if "selector" in p:
                return safari_actions.click_element(p["selector"])
            elif "text" in p:
                return safari_actions.click_element_by_text(p["text"], p.get("tag", "*"))
            else:
                return "ERROR: click_element needs 'selector' or 'text'"

        elif t == "type_text":
            if "selector" in p:
                return safari_actions.type_text(p["selector"], p["text"])
            else:
                return safari_actions.type_text_by_keystroke(p["text"])

        elif t == "key_press":
            key = p["key"]
            modifiers = p.get("modifiers")
            return safari_actions.press_key(key, modifiers)

        elif t == "mouse_click":
            return mouse.mouse_click(int(p["x"]), int(p["y"]))

        elif t == "scroll":
            return safari_actions.scroll_page(
                p.get("direction", "down"),
                int(p.get("amount", 300)),
            )

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
