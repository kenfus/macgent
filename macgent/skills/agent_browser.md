# agent-browser Skill

Headless browser automation CLI for AI agents with stealth anti-detection capabilities. This skill provides fast, reliable browser control using the Vercel Labs agent-browser CLI wrapped in Python with realistic headers and fingerprint spoofing.

## Overview

The agent-browser skill enables AI agents to:
- Navigate websites with realistic browser fingerprints
- Extract page content via accessibility tree snapshots
- Interact with elements using selectors or refs
- Take screenshots and capture page state
- Bypass bot detection on protected sites (DataDome, Cloudflare, etc.)

## Installation

The agent-browser CLI must be installed globally:

```bash
npm install -g agent-browser
agent-browser install  # Download Chromium
```

Or via Homebrew (macOS):

```bash
brew install agent-browser
agent-browser install
```

## Python API

### Basic Usage

```python
from macgent.actions.agent_browser import AgentBrowser, StealthConfig

# Create a browser with default stealth config
config = StealthConfig(headed=True)  # headed mode is harder to detect

with AgentBrowser(config) as browser:
    # Navigate to a URL
    browser.open('https://example.com')
    
    # Inject fingerprint spoofing (anti-detection)
    browser.inject_fingerprint_spoof()
    
    # Get page snapshot for AI analysis
    snapshot = browser.snapshot(interactive=True)
    
    # Interact with elements
    browser.click('@e5')  # Click by ref from snapshot
    browser.fill('@e10', 'search query')
    browser.press('Enter')
    
    # Take screenshot
    browser.screenshot('output.png')
```

### Site-Specific Configuration

```python
from macgent.actions.agent_browser import create_stealth_config_for_site

# Optimized config for specific sites
config = create_stealth_config_for_site('https://homegate.ch')
# - Uses headed mode (harder to detect)
# - Swiss German locale (de-CH)
# - Realistic Chrome/macOS headers
```

### Stealth Configuration Options

```python
from macgent.actions.agent_browser import StealthConfig

config = StealthConfig(
    browser_name='chrome',      # chrome, firefox, safari, edge
    browser_min_version=120,    # Minimum browser version
    os_name='macos',            # macos, windows, linux
    locale=['en-US', 'de-CH'],  # Accept-Language preference
    http_version=2,             # HTTP/2
    headed=True,                # Show browser window
    proxy='http://localhost:8080',  # Optional proxy
    color_scheme='light',       # light, dark
)
```

## Core Commands

### Navigation

| Method | Description |
|--------|-------------|
| `open(url)` | Navigate to URL with stealth headers |
| `back()` | Go back in history |
| `forward()` | Go forward in history |
| `reload()` | Reload current page |
| `get_url()` | Get current URL |
| `get_title()` | Get page title |

### Page Analysis

| Method | Description |
|--------|-------------|
| `snapshot(interactive=True)` | Get accessibility tree with element refs |
| `get_text(selector?)` | Get text content |
| `get_html(selector?)` | Get HTML content |
| `screenshot(path, full_page=False)` | Take screenshot |
| `eval_js(script)` | Execute JavaScript |

### Interaction

| Method | Description |
|--------|-------------|
| `click(selector)` | Click element by selector or @ref |
| `fill(selector, text)` | Clear and fill input |
| `type_text(selector, text)` | Type without clearing |
| `press(key)` | Press key (Enter, Tab, Escape, etc.) |
| `hover(selector)` | Hover over element |
| `scroll(direction, pixels)` | Scroll page |
| `wait(selector_or_ms)` | Wait for element or time |

### Tabs & Windows

| Method | Description |
|--------|-------------|
| `new_tab(url?)` | Open new tab |
| `switch_tab(n)` | Switch to tab n |
| `close_tab(n?)` | Close tab |
| `list_tabs()` | List all tabs |

### Cookies & Storage

| Method | Description |
|--------|-------------|
| `get_cookies()` | Get all cookies |
| `set_cookie(name, value, **options)` | Set cookie |
| `clear_cookies()` | Clear all cookies |

## Anti-Detection Features

### Realistic Headers (via browserforge)

Headers are automatically generated to match a real Chrome browser on macOS:

```
sec-ch-ua: "Chromium";v="144", "Google Chrome";v="144"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "macOS"
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,...
Accept-Language: de-CH;q=1.0, de;q=0.9, en-US;q=0.8
Sec-Fetch-Site: ?1
Sec-Fetch-Mode: same-site
Sec-Fetch-User: document
Sec-Fetch-Dest: navigate
```

### Fingerprint Spoofing

Call `inject_fingerprint_spoof()` after navigation to:

- Hide `navigator.webdriver` property
- Spoof WebGL renderer (Intel Iris)
- Add canvas noise to prevent fingerprinting
- Override AudioContext
- Remove automation indicators
- Fake Chrome runtime object
- Override navigator properties (plugins, languages, hardwareConcurrency)

### Browser Arguments

Default stealth arguments include:

```
--disable-blink-features=AutomationControlled
--disable-features=IsolateOrigins,site-per-process
--no-sandbox
--disable-infobars
--lang=en-US
```

## Working with Snapshots

The `snapshot(interactive=True)` method returns an accessibility tree optimized for AI agents:

```python
snapshot = browser.snapshot(interactive=True)

# Elements have refs like @e1, @e2, etc.
for element in snapshot.get('elements', []):
    print(f"{element['ref']}: {element.get('role')} - {element.get('name')}")
    
    # Click by ref
    browser.click(element['ref'])
```

## Example: Search on homegate.ch

```python
from macgent.actions.agent_browser import AgentBrowser, create_stealth_config_for_site
import time

config = create_stealth_config_for_site('https://homegate.ch')

with AgentBrowser(config) as browser:
    # Open homegate.ch
    browser.open('https://homegate.ch')
    time.sleep(2)
    
    # Inject anti-detection
    browser.inject_fingerprint_spoof()
    
    # Get snapshot to find elements
    snapshot = browser.snapshot(interactive=True)
    
    # Find and click "Buy" filter
    # ... interact with page based on snapshot
    
    # Take screenshot of results
    browser.screenshot('results.png')
```

## CLI Reference (agent-browser)

The underlying CLI can also be used directly:

```bash
# Navigation
agent-browser open example.com
agent-browser back
agent-browser forward
agent-browser reload

# Page info
agent-browser snapshot              # Accessibility tree
agent-browser screenshot page.png   # Screenshot
agent-browser get text              # Page text
agent-browser get url               # Current URL

# Interaction
agent-browser click "@e5"           # Click by ref
agent-browser fill "@e10" "text"    # Fill input
agent-browser press Enter           # Press key
agent-browser scroll down 500       # Scroll

# Stealth options
agent-browser open example.com --headed
agent-browser open example.com --user-agent "Mozilla/5.0..."
agent-browser open example.com --headers '{"X-Custom": "value"}'
```

## Configuration File

Create `agent-browser.json` for persistent defaults:

```json
{
  "headed": true,
  "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
  "colorScheme": "light",
  "proxy": "http://localhost:8080"
}
```

## Troubleshooting

### Bot Detection

If still detected as a bot:
1. Use `headed=True` (non-headless mode)
2. Add delays between actions (`time.sleep()`)
3. Use a persistent profile to maintain cookies
4. Consider using the Kernel cloud provider for advanced stealth

### Element Not Found

- Use `snapshot(interactive=True)` to get current element refs
- Elements may change after page updates - refresh snapshot
- Use `wait(selector)` to wait for elements to appear

### Timeout Errors

- Increase timeout: `browser._run_command(..., timeout=60.0)`
- Check network connectivity
- Verify the site is accessible

## See Also

- [agent-browser GitHub](https://github.com/vercel-labs/agent-browser)
- [browserforge](https://github.com/daijro/browserforge) - Header generation
- [Playwright](https://playwright.dev/) - Underlying browser automation
