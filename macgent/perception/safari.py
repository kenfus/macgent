import subprocess
import json
import time
import logging

logger = logging.getLogger("macgent.safari")


def run_osascript(script: str, timeout: int = 10) -> str:
    """Execute AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def get_safari_url() -> str:
    return run_osascript('tell application "Safari" to get URL of current tab of front window')


def get_safari_title() -> str:
    return run_osascript('tell application "Safari" to get name of current tab of front window')


def execute_js_in_safari(js_code: str, timeout: int = 15) -> str:
    """Execute JavaScript in the current Safari tab via AppleScript."""
    # Escape for embedding in AppleScript string
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f'tell application "Safari" to do JavaScript "{escaped}" in current tab of front window'
    return run_osascript(script, timeout=timeout)


def get_page_text(max_chars: int = 4000) -> str:
    """Get page text via document.body.innerText."""
    js = f"document.body.innerText.substring(0, {max_chars})"
    return execute_js_in_safari(js)


def get_page_interactive_elements(max_elements: int = 50) -> str:
    """Find clickable/interactive elements with their selectors and positions."""
    js = """
    (function() {
        var elements = [];
        var selectors = 'a, button, input, select, textarea, [role="button"], [onclick], [contenteditable="true"]';
        var nodes = document.querySelectorAll(selectors);
        for (var i = 0; i < Math.min(nodes.length, """ + str(max_elements) + """); i++) {
            var el = nodes[i];
            var rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            var text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').substring(0, 80);
            var tag = el.tagName.toLowerCase();
            var type = el.getAttribute('type') || '';
            var id = el.id ? '#' + el.id : '';
            var cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
            var selector = tag + id + cls;
            elements.push({
                i: elements.length,
                tag: tag,
                type: type,
                text: text.trim(),
                selector: selector.substring(0, 120),
                x: Math.round(rect.x + rect.width/2),
                y: Math.round(rect.y + rect.height/2)
            });
        }
        return JSON.stringify(elements);
    })()
    """
    result = execute_js_in_safari(js)
    return result


def wait_for_page_load(timeout: int = 10) -> bool:
    """Wait until document.readyState is 'complete'."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            state = execute_js_in_safari("document.readyState")
            if state == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False
