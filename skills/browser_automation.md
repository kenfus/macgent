# Browser Automation Skill

Control Safari browser to navigate websites, click elements, type text, and extract information from web pages.

## Actions

### navigate
Navigate to a URL in the browser.

```
Action: navigate
Params: {"url": "https://example.com"}
```

Example: Go to a specific website
- Opens the URL in Safari
- Waits for the page to load
- Returns to observe the new page

### click
Click on an interactive element on the page.

```
Action: click
Params: {"index": 5}
```

You must use the **element index number** provided in the interactive elements list. Always prefer using the element index for reliability.

### click_element
Click on an element identified by text.

```
Action: click_element
Params: {"text": "Search", "type": "button"}
```

This is less reliable than clicking by index. Use `click` with index when possible.

### type
Type text into a focused element (e.g., search box, input field).

```
Action: type
Params: {"text": "my search query"}
```

**Important**: The element must be focused first. Click the input field before typing.

### press_key
Press a keyboard key or combination.

```
Action: press_key
Params: {"key": "Return"}
```

Common keys:
- `Return` or `Enter` - submit forms, search
- `Tab` - move to next field
- `Escape` - close modals, cancel
- `Space` - scroll, toggle checkboxes
- `ArrowDown`, `ArrowUp` - navigate lists
- `cmd+a` - select all text

### scroll
Scroll the page in a direction.

```
Action: scroll
Params: {"direction": "down", "amount": 500}
```

Directions:
- `down` - scroll down
- `up` - scroll up
- `amount` - pixels to scroll

### wait
Wait for a certain amount of time (in seconds).

```
Action: wait
Params: {"seconds": 2}
```

Use when:
- Page is loading (though page load detection is automatic)
- Waiting for async content
- Waiting for animations to complete

### new_tab
Open a new browser tab.

```
Action: new_tab
Params: {}
```

### switch_tab
Switch to a different tab.

```
Action: switch_tab
Params: {"tab_number": 2}
```

### go_back
Go back to the previous page.

```
Action: go_back
Params: {}
```

### go_forward
Go forward to the next page.

```
Action: go_forward
Params: {}
```

## Observation

After each action, you observe:

- **URL**: Current page URL
- **Title**: Page title
- **Page Text**: All readable text on the page
- **Interactive Elements**: Buttons, links, input fields, etc. with index numbers
- **Page Structure**: Layout and form fields

## Common Patterns

### Simple Search
1. Navigate to search website
2. Click the search input (by index)
3. Type the search query
4. Press Return
5. Wait for results to load
6. Extract results from page text

### Form Submission
1. Click first input field by index
2. Type value
3. Tab to next field
4. Type value
5. Continue until form complete
6. Click submit button

### Handling Popups
Popups (cookie consent, login, newsletters) often block the page:
1. Look for "Close" or "X" button in the popup
2. Click it to dismiss
3. If not found, press Escape key
4. Reload the page if needed

### Multi-page Navigation
1. Navigate to first page
2. Extract data
3. Find "Next" link by index or element text
4. Click next link
5. Repeat from step 2

## Tips & Gotchas

- **Always use element index for clicking** - text matching is unreliable on complex pages
- **Wait after navigation** - Page loads are detected automatically, but give it 0.5-1 second
- **For forms, use Tab** - More reliable than trying to click each field
- **SPAs are tricky** - Single-page apps (Notion, Booking.com, Gmail) don't reload on navigation. Watch for loading indicators.
- **Screenshots lie** - Always check what the agent actually sees via extracted text and interactive elements
- **Cookie popups first** - Dismiss consent/cookie popups BEFORE trying other actions
- **Element indices change** - After page updates, element indices might shift. Re-observe before the next action.

## JavaScript Alternative

For complex data extraction or interactions, consider using the **JavaScript Execution** skill to run code directly in the page context.
