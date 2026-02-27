import time
import logging
import json
from macgent.utils_osascript import run_osascript

logger = logging.getLogger("macgent.safari")


def get_safari_url() -> str:
    return run_osascript('tell application "Safari" to get URL of current tab of front window')


def get_safari_title() -> str:
    return run_osascript('tell application "Safari" to get name of current tab of front window')


def execute_js_in_safari(js_code: str, timeout: int = 30) -> str:
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


def get_page_interactive_elements(max_elements: int = 80) -> str:
    """Find interactive elements, tag them with data-mid, return structured list.

    Each element gets a numeric index [0], [1], etc. that the agent can reference.
    Elements are tagged in the DOM so actions can find them by index.

    Two-pass strategy: calendar/overlay elements are always listed first (React portals
    append to body end and would otherwise be cut off by the max_elements cap).
    """
    js = """
    (function() {
        var MAX = """ + str(max_elements) + """;

        // Clear old tags
        document.querySelectorAll('[data-mid]').forEach(function(el) {
            el.removeAttribute('data-mid');
        });

        var elements = [];
        var seen = new Set ? new Set() : {
            _s: [], has: function(x){ return this._s.indexOf(x) >= 0; },
            add: function(x){ this._s.push(x); }
        };
        var idx = 0;

        function isVisible(el) {
            var rect = el.getBoundingClientRect();
            if (rect.width < 2 || rect.height < 2) return false;
            if (rect.bottom < 0 || rect.top > window.innerHeight + 300) return false;
            if (rect.right < 0 || rect.left > window.innerWidth) return false;
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            return true;
        }

        function describeEl(el) {
            el.setAttribute('data-mid', idx);
            var tag = el.tagName.toLowerCase();
            var type = el.getAttribute('type') || '';
            var text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.title || '').trim().substring(0, 60);
            var href = el.getAttribute('href') || '';
            var name = el.getAttribute('name') || '';
            var role = el.getAttribute('role') || '';
            var dataDate = el.getAttribute('data-date') || '';
            var dataTestId = el.getAttribute('data-testid') || '';

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
                var selected = el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
                desc += 'SELECT';
                if (name) desc += ' name=' + name;
                desc += ' selected="' + selected + '"';
                var opts = [];
                for (var j = 0; j < Math.min(el.options ? el.options.length : 0, 5); j++) {
                    opts.push(el.options[j].text);
                }
                if (el.options && el.options.length > 5) opts.push('...');
                desc += ' options=[' + opts.join(', ') + ']';
            } else if (tag === 'textarea') {
                desc += 'TEXTAREA';
                if (name) desc += ' name=' + name;
                if (el.placeholder) desc += ' placeholder="' + el.placeholder + '"';
                if (el.value) desc += ' value="' + el.value.substring(0, 40) + '"';
            } else {
                desc += tag.toUpperCase();
                if (role) desc += '[role=' + role + ']';
                if (dataDate) desc += ' date=' + dataDate;
                if (dataTestId) desc += ' testid=' + dataTestId;
                // Show selection/disabled state for calendar cells
                if (el.getAttribute('aria-selected') === 'true') desc += ' [selected]';
                if (el.getAttribute('aria-disabled') === 'true') desc += ' [disabled]';
                desc += ' "' + text + '"';
            }
            return desc;
        }

        function processNodes(nodes) {
            for (var i = 0; i < nodes.length && idx < MAX; i++) {
                var el = nodes[i];
                if (seen.has(el)) continue;
                if (!isVisible(el)) continue;
                seen.add(el);
                elements.push(describeEl(el));
                idx++;
            }
        }

        // Pass 1: Calendar cells — always extract first (React portals live at end of body)
        // These are the most important when a date picker is open
        processNodes(document.querySelectorAll('[data-date]'));
        processNodes(document.querySelectorAll('[role="gridcell"]'));

        // Pass 2: Standard interactive elements
        var stdSelectors = [
            'a[href]', 'button', 'input', 'select', 'textarea',
            '[role="button"]', '[role="link"]', '[role="tab"]',
            '[role="menuitem"]', '[role="option"]',
            '[role="checkbox"]', '[role="radio"]', '[role="switch"]',
            '[onclick]', '[contenteditable="true"]', 'summary', 'details',
            '[tabindex="0"]', '[tabindex="-1"]',
            '[data-testid]',
            '[aria-selected]', '[aria-checked]', '[aria-expanded]',
        ].join(', ');
        processNodes(document.querySelectorAll(stdSelectors));

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

        // Google Sheets: current cell reference (Name Box) and formula bar content
        var nameBox = document.querySelector('input.waffle-name-box');
        if (nameBox && nameBox.value) {
            parts.push('CURRENT CELL: ' + nameBox.value);
        }
        var formulaBar = document.querySelector('.cell-input');
        if (formulaBar && formulaBar.textContent) {
            parts.push('CELL CONTENT: ' + formulaBar.textContent.trim().substring(0, 80));
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
