import time
import logging
from macgent.perception.safari import run_osascript, execute_js_in_safari

logger = logging.getLogger("macgent.actions.safari")


def ensure_safari_window(url: str = "about:blank") -> None:
    """Ensure Safari is open and has at least one window. Opens one if needed."""
    run_osascript('tell application "Safari" to activate')
    time.sleep(0.5)
    # Check if there's a front window
    check = '''
    tell application "Safari"
        if (count of windows) = 0 then
            make new document with properties {URL:"''' + url + '''"}
        else if (count of tabs of front window) = 0 then
            tell front window to make new tab with properties {URL:"''' + url + '''"}
        end if
    end tell
    '''
    try:
        run_osascript(check)
        time.sleep(1)
    except Exception as e:
        logger.warning(f"ensure_safari_window failed: {e}")


def navigate(url: str) -> str:
    """Navigate Safari to a URL. Opens a window if none exists."""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    escaped = url.replace('"', '\\"')

    # Try direct navigation first; if it fails because there's no window, open one
    script = f'tell application "Safari" to set URL of current tab of front window to "{escaped}"'
    try:
        run_osascript(script)
    except RuntimeError:
        # No front window — open Safari with the URL directly
        ensure_safari_window(url)
        run_osascript(f'tell application "Safari" to set URL of current tab of front window to "{escaped}"')

    run_osascript('tell application "Safari" to activate')
    time.sleep(2)
    return f"Navigated to {url}"


def go_back() -> str:
    """Go back in browser history."""
    execute_js_in_safari("history.back()")
    time.sleep(1)
    return "Went back"


def go_forward() -> str:
    """Go forward in browser history."""
    execute_js_in_safari("history.forward()")
    time.sleep(1)
    return "Went forward"


def click_element_by_index(index: int) -> str:
    """Click an element by its macgent index (from element list)."""
    js = f"""
    (function() {{
        var el = document.querySelector('[data-mid="{index}"]');
        if (!el) return 'ERROR: Element [{index}] not found. Page may have changed.';
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        el.focus();
        el.click();
        el.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
        el.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
        el.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
        var text = (el.innerText || el.value || el.getAttribute('aria-label') || '').substring(0, 50);
        return 'Clicked [' + {index} + '] ' + el.tagName.toLowerCase() + ': ' + text;
    }})()
    """
    return execute_js_in_safari(js)


def click_element(selector: str) -> str:
    """Click a DOM element by CSS selector."""
    escaped = selector.replace("'", "\\'")
    js = f"""
    (function() {{
        var el = document.querySelector('{escaped}');
        if (!el) return 'ERROR: Element not found: {escaped}';
        el.scrollIntoView({{block: 'center'}});
        el.focus();
        el.click();
        el.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
        return 'Clicked: ' + el.tagName + ' ' + (el.innerText || '').substring(0, 50);
    }})()
    """
    return execute_js_in_safari(js)


def click_element_by_text(text: str, tag: str = "*") -> str:
    """Click an element by its visible text content."""
    escaped = text.replace("'", "\\'").replace('"', '\\"')
    js = f"""
    (function() {{
        var xpath = "//{tag}[contains(text(), '{escaped}')]";
        var result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        var el = result.singleNodeValue;
        if (!el) return 'ERROR: No element with text: {escaped}';
        el.scrollIntoView({{block: 'center'}});
        el.focus();
        el.click();
        el.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
        return 'Clicked element with text: ' + el.innerText.substring(0, 50);
    }})()
    """
    return execute_js_in_safari(js)


def type_text_by_index(index: int, text: str) -> str:
    """Clear and type text into an element by its macgent index."""
    escaped_text = text.replace("'", "\\'").replace("\\", "\\\\")
    js = f"""
    (function() {{
        var el = document.querySelector('[data-mid="{index}"]');
        if (!el) return 'ERROR: Element [{index}] not found.';
        el.scrollIntoView({{block: 'center'}});
        el.focus();
        if (el.select) el.select();
        el.value = '{escaped_text}';
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'Typed into [' + {index} + ']: ' + el.tagName.toLowerCase();
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
        if (el.select) el.select();
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


def select_option_by_index(index: int, value: str) -> str:
    """Select a dropdown option by element index and option text/value."""
    escaped = value.replace("'", "\\'")
    js = f"""
    (function() {{
        var el = document.querySelector('[data-mid="{index}"]');
        if (!el) return 'ERROR: Element [{index}] not found.';
        if (el.tagName !== 'SELECT') return 'ERROR: Element [{index}] is not a SELECT.';
        var found = false;
        for (var i = 0; i < el.options.length; i++) {{
            if (el.options[i].text.indexOf('{escaped}') !== -1 || el.options[i].value === '{escaped}') {{
                el.selectedIndex = i;
                found = true;
                break;
            }}
        }}
        if (!found) return 'ERROR: Option not found.';
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'Selected "' + el.options[el.selectedIndex].text + '" in [' + {index} + ']';
    }})()
    """
    return execute_js_in_safari(js)


def press_key(key: str, modifiers: list[str] | None = None) -> str:
    """Press a key via AppleScript. Supports modifiers like cmd, shift, option, control."""
    key_codes = {
        "return": 36, "enter": 36, "tab": 48, "escape": 53,
        "delete": 51, "backspace": 51, "space": 49,
        "down": 125, "up": 126, "left": 123, "right": 124,
        "f5": 96, "home": 115, "end": 119,
        "pageup": 116, "pagedown": 121,
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


def scroll_page(direction: str = "down", amount: int = 500) -> str:
    """Scroll the page via JavaScript."""
    if direction == "top":
        execute_js_in_safari("window.scrollTo(0, 0)")
        return "Scrolled to top"
    elif direction == "bottom":
        execute_js_in_safari("window.scrollTo(0, document.body.scrollHeight)")
        return "Scrolled to bottom"
    dy = amount if direction == "down" else -amount
    execute_js_in_safari(f"window.scrollBy(0, {dy})")
    return f"Scrolled {direction} by {amount}px"


def new_tab(url: str = "") -> str:
    """Open a new Safari tab, optionally with a URL. Opens a window if none exists."""
    ensure_safari_window()
    if url:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        escaped = url.replace('"', '\\"')
        run_osascript(f'''
            tell application "Safari"
                tell front window to make new tab with properties {{URL:"{escaped}"}}
                activate
            end tell
        ''')
        time.sleep(2)
        return f"Opened new tab: {url}"
    else:
        run_osascript('''
            tell application "Safari"
                tell front window to make new tab
                activate
            end tell
        ''')
        return "Opened new empty tab"


def close_tab() -> str:
    """Close the current Safari tab."""
    run_osascript('tell application "Safari" to close current tab of front window')
    return "Closed current tab"


def switch_tab(tab_number: int) -> str:
    """Switch to a specific tab by number (1-based)."""
    run_osascript(f'tell application "Safari" to set current tab of front window to tab {tab_number} of front window')
    time.sleep(0.5)
    return f"Switched to tab {tab_number}"
