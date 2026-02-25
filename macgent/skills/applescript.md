# AppleScript Automation Skill

Execute AppleScript commands to automate macOS applications and system features.

## Action

### applescript
Execute arbitrary AppleScript code.

```
Action: applescript
Params: {
    "script": "tell app \"Finder\" to activate"
}
```

Parameters:
- `script` - AppleScript code as string (required)

Returns:
- Script output
- Any error messages
- Exit status

## Common Patterns

### Activate an Application
```applescript
tell app "Finder" to activate
tell app "Slack" to activate
tell app "Spotify" to activate
```

### Get Information from System
```applescript
tell application "System Events"
    get name of every process
end tell
```

### Control Media Playback
```applescript
tell application "Spotify"
    play
    pause
    next track
end tell
```

### Open Files/Folders
```applescript
tell app "Finder"
    open POSIX file "/Users/username/Downloads"
end tell
```

### Run Shell Commands
```applescript
do shell script "ls -la /Users/username/Documents"
```

### Control System Settings
```applescript
tell application "System Events"
    set volume output volume 50
end tell
```

## Examples

### Open Browser to URL
```applescript
tell application "Safari"
    activate
    open location "https://example.com"
end tell
```

### Get List of Running Apps
```applescript
tell application "System Events"
    get name of every process where background only is false
end tell
```

### Send Notification
```applescript
display notification "Task complete!" with title "macgent"
```

### Check Current Time
```applescript
tell application "System Events"
    get current date
end tell
```

## Tips & Gotchas

- **AppleScript permissions** - Scripts may need System Events permission
- **App names matter** - Use exact app name from Finder
- **Background apps** - Can't control apps that don't expose AppleScript interface
- **Error handling** - Long or complex scripts may fail; keep scripts simple
- **Delays needed** - Add `delay 1` between rapid commands if app needs time to respond
- **Shell scripts dangerous** - Using `do shell script` with untrusted input is a security risk
- **Encoding** - Script content should be valid UTF-8

## When to Use AppleScript vs Browser Automation

| Task | Browser | AppleScript |
|------|---------|-------------|
| Control Safari | ✓ | ✓ (browser automation easier) |
| Control Finder | | ✓ |
| Manage files | | ✓ |
| Run terminal commands | | ✓ |
| Control system volume | | ✓ |
| Control other Mac apps | | ✓ |
| Extract web page data | ✓ (better) | |

## Related Skills

- [Browser Automation](./browser_automation.md) - For web-based tasks
- [JavaScript Execution](./javascript.md) - For complex page automation
