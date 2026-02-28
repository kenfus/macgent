# Skill: AppleScript

Execute arbitrary AppleScript to control macOS apps and system features.

```json
{"type": "applescript", "params": {"script": "tell application \"Finder\" to activate"}}
```

- `script` — AppleScript source string (required)
- Add `delay 1` between rapid commands if an app needs time to respond
- Use for: Finder, Spotify, System Events, volume, notifications, shell commands via `do shell script`
- Prefer browser automation for Safari/web tasks
