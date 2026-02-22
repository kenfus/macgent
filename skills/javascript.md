# JavaScript Execution Skill

Run JavaScript code directly in the browser page context to extract data, manipulate elements, and interact with single-page applications.

## Action

### javascript
Execute JavaScript in the current browser page.

```
Action: javascript
Params: {
    "code": "return document.title"
}
```

Parameters:
- `code` - JavaScript code as string (required)
- Should include `return` statement with result

Returns:
- Result of the last expression
- JSON serializable data (strings, numbers, arrays, objects)
- null if no return value

## Common Patterns

### Extract Page Title
```javascript
return document.title
```

### Get All Links on Page
```javascript
return Array.from(document.querySelectorAll('a'))
    .map(a => ({text: a.textContent, href: a.href}))
```

### Extract Table Data
```javascript
return Array.from(document.querySelectorAll('table tbody tr'))
    .map(row => ({
        cells: Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim())
    }))
```

### Find Element by Text
```javascript
return Array.from(document.querySelectorAll('button'))
    .find(btn => btn.textContent.includes('Search'))
    ?.getBoundingClientRect()
```

### Get Form Input Values
```javascript
return {
    email: document.querySelector('input[type="email"]').value,
    password: document.querySelector('input[type="password"]').value
}
```

### Check if Element is Visible
```javascript
const elem = document.querySelector('.hidden-panel');
const style = window.getComputedStyle(elem);
return style.display !== 'none' && style.visibility !== 'hidden'
```

### Get All Text Content
```javascript
return document.body.innerText
```

### Extract JSON from Page
For pages that embed JSON data:
```javascript
return JSON.parse(document.getElementById('data-json').textContent)
```

### Simulate User Input (Advanced)
```javascript
// Set input value
const input = document.querySelector('input[name="search"]');
input.value = "my search";

// Trigger input event for frameworks to notice
input.dispatchEvent(new Event('input', {bubbles: true}));

return "Input updated"
```

### Wait for Element (Advanced)
```javascript
return new Promise(resolve => {
    const checkElement = () => {
        const elem = document.querySelector('.dynamic-content');
        if (elem && elem.textContent) {
            resolve(elem.textContent);
        } else {
            setTimeout(checkElement, 100);
        }
    };
    checkElement();
});
```

## Advanced Features

### Single Page App (SPA) Detection
```javascript
// Check if page is a React/Vue/Angular app
const hasReactDevTools = window.__REACT_DEVTOOLS_GLOBAL_HOOK__ !== undefined;
const hasVue = window.__VUE__ !== undefined;
return {
    isReact: hasReactDevTools,
    isVue: hasVue,
    isAngular: window.ng !== undefined
}
```

### Get Page State (React)
For React apps, if exposed:
```javascript
return window.__REACT_DEVTOOLS_GLOBAL_HOOK__.renderers
```

### Scroll and Get Dynamic Content
```javascript
window.scrollBy(0, window.innerHeight);
return new Promise(resolve => {
    setTimeout(() => {
        resolve(document.body.innerText.slice(0, 1000));
    }, 500);
});
```

## Tips & Gotchas

- **Must return JSON-serializable data** - Can't return DOM elements directly
- **Page context only** - JavaScript runs in the page context, has access to page data
- **Same-origin policy** - Can't access iframes from different origins
- **No direct element clicking** - Use Browser Automation skill for interaction
- **Async limitations** - Can use Promises but execution must complete
- **Console errors ignored** - Errors don't stop execution, check return value
- **Personal data exposed** - JavaScript has access to page data including auth tokens
- **SPAs are the strength** - JavaScript is best for extracting data from complex SPAs

## When to Use JavaScript vs Browser Automation

| Task | Browser Automation | JavaScript |
|------|-------------------|------------|
| Click button | ✓ (better) | |
| Type in input | ✓ (better) | |
| Navigate page | ✓ (better) | |
| Extract visible text | ✓ | ✓ |
| Extract hidden data | | ✓ |
| Read JavaScript objects | | ✓ |
| Read embedded JSON | | ✓ |
| Wait for dynamic content | | ✓ |
| Access SPA state | | ✓ |
| Scroll and load | ✓ | ✓ (complex) |

## Performance Notes

- JavaScript execution is faster than clicking/typing multiple times
- Use JS to extract all needed data at once rather than multiple observations
- For data-heavy extraction, JavaScript is much more efficient

## Related Skills

- [Browser Automation](./browser_automation.md) - For navigation and clicks
- [AppleScript](./applescript.md) - For system-level automation
