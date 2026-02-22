import subprocess
import json
import time
import logging

logger = logging.getLogger("macgent.safari")


def run_osascript(script: str, timeout: int = 10) -> str:
    """Execute AppleScript and return stdout. Retries once on timeout."""
    for attempt in range(2):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            if attempt == 0:
                logger.warning(f"osascript timed out after {timeout}s, retrying...")
                time.sleep(2)
                timeout = int(timeout * 1.5)
                continue
            raise RuntimeError(f"osascript timed out after {timeout}s (Safari may be busy)")


def get_safari_url() -> str:
    return run_osascript('tell application "Safari" to get URL of current tab of front window')


def get_safari_title() -> str:
    return run_osascript('tell application "Safari" to get name of current tab of front window')


def execute_js_in_safari(js_code: str, timeout: int = 15) -> str:
    """Execute JavaScript in the current Safari tab via AppleScript."""
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f'tell application "Safari" to do JavaScript "{escaped}" in current tab of front window'
    return run_osascript(script, timeout=timeout)


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


def get_page_text(max_chars: int = 4000) -> str:
    """Get page text via document.body.innerText."""
    js = f"document.body.innerText.substring(0, {max_chars})"
    return execute_js_in_safari(js)


def get_page_interactive_elements(max_elements: int = 40) -> str:
    """Find interactive elements, tag them with data-macgent-id, return structured list.

    Each element gets a numeric index [0], [1], etc. that the agent can reference.
    Elements are tagged in the DOM so actions can find them by index.
    """
    js = """
    (function() {
        // Clear old tags
        document.querySelectorAll('[data-mid]').forEach(function(el) {
            el.removeAttribute('data-mid');
        });

        var elements = [];
        var selectors = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [onclick], [contenteditable="true"], summary, details';
        var nodes = document.querySelectorAll(selectors);
        var idx = 0;

        for (var i = 0; i < nodes.length && idx < """ + str(max_elements) + """; i++) {
            var el = nodes[i];
            var rect = el.getBoundingClientRect();

            // Skip invisible/offscreen elements
            if (rect.width < 2 || rect.height < 2) continue;
            if (rect.bottom < 0 || rect.top > window.innerHeight + 200) continue;
            if (rect.right < 0 || rect.left > window.innerWidth) continue;

            // Skip hidden elements
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

            // Tag element for later reference
            el.setAttribute('data-mid', idx);

            var tag = el.tagName.toLowerCase();
            var type = el.getAttribute('type') || '';
            var text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.title || '').trim().substring(0, 60);
            var href = el.getAttribute('href') || '';
            var name = el.getAttribute('name') || '';
            var role = el.getAttribute('role') || '';

            // Build a readable description
            var desc = '[' + idx + '] ';
            if (tag === 'a') {
                desc += 'LINK "' + text + '"';
                if (href && href.length < 80 && href !== '#') desc += ' -> ' + href;
            } else if (tag === 'button' || role === 'button') {
                desc += 'BUTTON "' + text + '"';
            } else if (tag === 'input') {
                var inputType = type || 'text';
                var val = el.value || '';
                desc += 'INPUT[' + inputType + ']';
                if (name) desc += ' name=' + name;
                if (el.placeholder) desc += ' placeholder="' + el.placeholder + '"';
                if (val && inputType !== 'password') desc += ' value="' + val.substring(0, 40) + '"';
                if (el.checked !== undefined) desc += el.checked ? ' [checked]' : ' [unchecked]';
            } else if (tag === 'select') {
                var selected = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
                desc += 'SELECT';
                if (name) desc += ' name=' + name;
                desc += ' selected="' + selected + '"';
                var opts = [];
                for (var j = 0; j < Math.min(el.options.length, 5); j++) {
                    opts.push(el.options[j].text);
                }
                if (el.options.length > 5) opts.push('...');
                desc += ' options=[' + opts.join(', ') + ']';
            } else if (tag === 'textarea') {
                desc += 'TEXTAREA';
                if (name) desc += ' name=' + name;
                if (el.placeholder) desc += ' placeholder="' + el.placeholder + '"';
                if (el.value) desc += ' value="' + el.value.substring(0, 40) + '"';
            } else {
                desc += tag.toUpperCase();
                if (role) desc += '[role=' + role + ']';
                desc += ' "' + text + '"';
            }

            elements.push(desc);
            idx++;
        }
        return elements.join('\\n');
    })()
    """
    return execute_js_in_safari(js)


def get_page_structure(max_chars: int = 2000) -> str:
    """Get a compact structural overview: headings, forms, nav landmarks."""
    js = """
    (function() {
        var parts = [];

        // Headings for page structure
        var headings = document.querySelectorAll('h1, h2, h3');
        if (headings.length > 0) {
            var hs = [];
            for (var i = 0; i < Math.min(headings.length, 8); i++) {
                var h = headings[i];
                hs.push(h.tagName + ': ' + h.innerText.trim().substring(0, 60));
            }
            parts.push('HEADINGS: ' + hs.join(' | '));
        }

        // Forms
        var forms = document.querySelectorAll('form');
        if (forms.length > 0) {
            parts.push('FORMS: ' + forms.length + ' form(s) on page');
        }

        // Current URL info
        parts.push('URL: ' + location.href);

        // Scroll position
        var scrollPct = Math.round(100 * window.scrollY / Math.max(1, document.body.scrollHeight - window.innerHeight));
        parts.push('SCROLL: ' + scrollPct + '% (' + Math.round(window.scrollY) + 'px of ' + document.body.scrollHeight + 'px)');

        // Focused element
        var focused = document.activeElement;
        if (focused && focused !== document.body) {
            var ft = focused.tagName.toLowerCase();
            var fn = focused.name || focused.id || '';
            parts.push('FOCUSED: ' + ft + (fn ? '[' + fn + ']' : ''));
        }

        return parts.join('\\n');
    })()
    """
    try:
        return execute_js_in_safari(js)
    except Exception:
        return ""


def get_safari_tab_count() -> int:
    """Get number of open Safari tabs."""
    try:
        result = run_osascript('tell application "Safari" to count tabs of front window')
        return int(result)
    except Exception:
        return 1
