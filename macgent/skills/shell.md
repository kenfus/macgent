# Shell

Run arbitrary shell commands in a **persistent tmux session** (`macgent_shell`).
State survives between calls: working directory, environment variables, background processes.

The user (or you) can attach to watch the terminal live:
```
tmux attach -t macgent_shell
```

## run_shell

```json
{"type": "run_shell", "params": {"command": "<shell command>"}}
{"type": "run_shell", "params": {"command": "cd ~/projects/foo && git status"}}
{"type": "run_shell", "params": {"command": "npm run dev", "timeout": 120}}
```

- `command` — any shell command (bash, zsh, etc.)
- `timeout` — seconds to wait for completion (default 60). For long-running processes, use a background job (`command &`) and check output separately.
- Returns stdout+stderr captured from the pane. Non-zero exit code appended as `[exit N]`.
- **State persists**: `cd` into a directory once and subsequent commands run there.
- **Long-running processes**: start with `&`, check with `jobs` or read output files.
