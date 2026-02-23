# Skill: Browser Automation (Safari)

## Core Rules

1. After navigating, **wait** for the page to load before acting
2. For search: type query then press **Return**
3. For forms: click input → type → Tab to next field
4. **Scroll down** to find more content if needed
5. If stuck on the same action 2+ times, try a **completely different approach**

## Element Interaction

Elements appear as:
```
[0] INPUT[text] placeholder="Search..."
[1] BUTTON "Search"
[2] LINK "About" -> /about
```

**Always prefer [index] numbers.** They are the most reliable.

## Popup Handling — CHECK FIRST on Every New Page

Popups block everything including scrolling. Handle them before any other action:

| Popup type       | What to click |
|-----------------|---------------|
| Cookie consent  | "Reject all", "Decline", or X |
| Login prompt    | "Continue as guest", "Close", X — NEVER log in via SSO |
| Newsletter      | Dismiss immediately |

A blocked popup = blocked page. Always dismiss first.

## Date Pickers (Booking.com, Airbnb, etc.)

1. Click the date field → calendar cells appear as `TD[role=gridcell] date=YYYY-MM-DD`
2. Click check-in date **ONCE** — it shows `[selected]`
3. Then **immediately** click check-out date
4. Do **NOT** click check-in again
5. Navigate months with "Next month" / "Previous month" if needed

## Extracting Results

1. **Read PAGE TEXT first** — names, prices, ratings are usually there
2. Compile from page text, then call `done` with a summary
3. Only use `execute_js` as a last resort when page text is clearly incomplete

## Domain-Specific Notes

- booking.com: wait ~2.5s after navigate; cookie popup at index [2]
- Google Maps: results appear as a list on the left side
- React/SPA sites: wait 1–2s for content to render
