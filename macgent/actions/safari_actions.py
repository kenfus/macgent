import time
import logging
from macgent.perception.safari import run_osascript, execute_js_in_safari

logger = logging.getLogger("macgent.actions.safari")


def navigate(url: str) -> str:
    """Navigate Safari to a URL."""
    run_osascript(f'tell application "Safari" to set URL of current tab of front window to "{url}"')
    run_osascript('tell application "Safari" to activate')
    time.sleep(2)
    return f"Navigated to {url}"


def click_element(selector: str) -> str:
    """Click a DOM element by CSS selector."""
    escaped = selector.replace("'", "\\'")
    js = f"""
    (function() {{
        var el = document.querySelector('{escaped}');
        if (!el) return 'ERROR: Element not found: {escaped}';
        el.scrollIntoView({{block: 'center'}});
        el.click();
        return 'Clicked: ' + el.tagName + ' ' + (el.innerText || '').substring(0, 50);
    }})()
    """
    return execute_js_in_safari(js)


def click_element_by_text(text: str, tag: str = "*") -> str:
    """Click an element by its visible text content."""
    escaped = text.replace("'", "\\'")
    js = f"""
    (function() {{
        var xpath = "//{tag}[contains(text(), '{escaped}')]";
        var result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        var el = result.singleNodeValue;
        if (!el) return 'ERROR: No element with text: {escaped}';
        el.scrollIntoView({{block: 'center'}});
        el.click();
        return 'Clicked element with text: ' + el.innerText.substring(0, 50);
    }})()
    """
    return execute_js_in_safari(js)


def type_text(selector: str, text: str) -> str:
    """Type text into an input element by CSS selector."""
    escaped_sel = selector.replace("'", "\\'")
    escaped_text = text.replace("'", "\\'").replace("\\", "\\\\")
    js = f"""
    (function() {{
        var el = document.querySelector('{escaped_sel}');
        if (!el) return 'ERROR: Element not found: {escaped_sel}';
        el.focus();
        el.value = '{escaped_text}';
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'Typed into: ' + el.tagName;
    }})()
    """
    return execute_js_in_safari(js)


def type_text_by_keystroke(text: str) -> str:
    """Type via AppleScript keystroke (for contenteditable, Notion blocks, etc.)."""
    escaped = text.replace('"', '\\"')
    script = f'tell application "System Events" to keystroke "{escaped}"'
    run_osascript(script)
    return f"Typed via keystroke: {text}"


def press_key(key: str, modifiers: list[str] | None = None) -> str:
    """Press a key via AppleScript. Supports modifiers like cmd, shift, option, control."""
    key_codes = {
        "return": 36, "enter": 36, "tab": 48, "escape": 53,
        "delete": 51, "space": 49, "down": 125, "up": 126,
        "left": 123, "right": 124, "f5": 96,
    }

    key_lower = key.lower()
    if key_lower in key_codes:
        code = key_codes[key_lower]
        cmd = f'key code {code}'
    else:
        escaped = key.replace('"', '\\"')
        cmd = f'keystroke "{escaped}"'

    if modifiers:
        mod_map = {"cmd": "command down", "shift": "shift down", "option": "option down", "control": "control down"}
        mod_str = ", ".join(mod_map.get(m, f"{m} down") for m in modifiers)
        script = f'tell application "System Events" to {cmd} using {{{mod_str}}}'
    else:
        script = f'tell application "System Events" to {cmd}'

    run_osascript(script)
    return f"Pressed key: {key}" + (f" with {modifiers}" if modifiers else "")


def scroll_page(direction: str = "down", amount: int = 300) -> str:
    """Scroll the page via JavaScript."""
    dy = amount if direction == "down" else -amount
    execute_js_in_safari(f"window.scrollBy(0, {dy})")
    return f"Scrolled {direction} by {amount}px"
