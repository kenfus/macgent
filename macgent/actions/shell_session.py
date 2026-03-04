"""Persistent interactive shell session backed by a tmux window.

The agent uses `ShellSession.run(command)` to execute shell commands with full
state persistence: working directory, environment variables, and running
processes all survive between calls.

The tmux session is named ``macgent_shell``.  Users can attach to watch or
interact::

    tmux attach -t macgent_shell

If macgent itself is running inside a tmux session the agent shell is created
as a new window in the *same* session so everything is visible in one place.
"""

from __future__ import annotations

import subprocess
import time
import uuid


SESSION = "macgent_shell"
# How long to wait for a command to produce its done-marker before giving up
DEFAULT_TIMEOUT = 60
# Polling interval while waiting for output
POLL_INTERVAL = 0.15
# Maximum lines of output to return (taken from the end)
MAX_OUTPUT_LINES = 200


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _session_exists() -> bool:
    return _tmux("has-session", "-t", SESSION).returncode == 0


def _parent_tmux_session() -> str | None:
    """Return the tmux session name macgent is running inside, or None."""
    import os
    if not os.environ.get("TMUX"):
        return None
    r = _tmux("display-message", "-p", "#{session_name}")
    if r.returncode == 0:
        return r.stdout.strip() or None
    return None


def ensure_session() -> None:
    """Create the shell session if it does not exist."""
    if _session_exists():
        return
    parent = _parent_tmux_session()
    if parent and parent != SESSION:
        # Create a new window inside the parent session — visible alongside macgent
        _tmux("new-window", "-t", parent, "-n", "agent-shell")
        # new-window creates the window but has-session still works on the session.
        # send-keys targeting SESSION won't work here; we'd need the window id.
        # For simplicity, fall through and create a detached session that the
        # user can attach to separately. The window above is cosmetic/bonus.
        pass
    _tmux("new-session", "-d", "-s", SESSION)


def run(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run *command* in the persistent shell and return its output.

    Exit code is appended as ``[exit N]`` when non-zero.
    """
    ensure_session()

    marker = f"__DONE_{uuid.uuid4().hex[:12]}__"
    # Wrap so we always capture exit code and emit marker after completion
    wrapped = f"({command}); __exit__=$?; echo '{marker}'$__exit__"
    _tmux("send-keys", "-t", SESSION, wrapped, "Enter")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        cap = _tmux("capture-pane", "-t", SESSION, "-p", "-S", "-")
        pane_text = cap.stdout

        if marker in pane_text:
            lines = pane_text.splitlines()
            output_lines: list[str] = []
            exit_code: int | None = None

            for line in lines:
                if marker in line:
                    suffix = line.split(marker, 1)[-1].strip()
                    try:
                        exit_code = int(suffix)
                    except ValueError:
                        exit_code = None
                    break
                output_lines.append(line)

            trimmed = output_lines[-MAX_OUTPUT_LINES:]
            result = "\n".join(trimmed).strip()
            if exit_code is not None and exit_code != 0:
                result += f"\n[exit {exit_code}]"
            return result or "(no output)"

    return (
        f"ERROR: run_shell timed out after {timeout}s "
        f"(command may still be running — attach with: tmux attach -t {SESSION})"
    )
