import sys
import logging
import shutil
import os
import json
from datetime import date
from pathlib import Path


def _update_env(env_path: Path, values: dict):
    """Add or update KEY=value entries in a .env file."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated = set()
    result = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values:
            result.append(f"{key}={values[key]}")
            updated.add(key)
        else:
            result.append(line)
    for key, val in values.items():
        if key not in updated:
            result.append(f"{key}={val}")
    env_path.write_text("\n".join(result) + "\n")


def _update_runtime_config(config_path: Path, runtime_values: dict):
    """Update runtime settings in macgent_config.json (create file if needed)."""
    data = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    runtime = data.get("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    runtime.update(runtime_values)
    data["runtime"] = runtime
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _run_setup_wizard(config, env_path: Path):
    """Interactive terminal setup for missing configuration.

    Only runs if Telegram (or other required config) is not set.
    Never involves the LLM — pure Python/terminal.
    Returns an updated config object.
    """
    has_workspace_in_cfg = bool(
        str(config.model_config.get("runtime", {}).get("workspace_dir", "")).strip()
    )
    needs_setup = (not has_workspace_in_cfg) or (not config.telegram_bot_token) or (not config.telegram_chat_id)
    if not needs_setup:
        return config

    print()
    print("=" * 60)
    print("  macgent — first-time setup")
    print("=" * 60)
    print(f"\nWorkspace: {config.workspace_dir}")
    print(f"Log file:  {config.log_file}")

    new_runtime = {}
    new_env = {}

    # ── Workspace (stored in config JSON, not .env) ──────────
    if not has_workspace_in_cfg:
        suggested_workspace = str((Path.cwd() / "workspace").resolve())
        raw_workspace = input(f"Workspace directory [{suggested_workspace}]: ").strip() or suggested_workspace
        workspace_dir = str(Path(raw_workspace).expanduser().resolve())
        new_runtime["workspace_dir"] = workspace_dir

    # ── Telegram ──────────────────────────────────────────────
    if not config.telegram_bot_token or not config.telegram_chat_id:
        print()
        print("Telegram is not configured.")
        print("The agent sends you updates and reads your replies via Telegram.")
        print()
        print("How to set up:")
        print("  1. Open Telegram → search @BotFather → send /newbot")
        print("  2. Follow the prompts — BotFather gives you an API token")
        print("  3. Start a chat with your new bot (send it any message)")
        print("  4. To find your chat ID: message @userinfobot in Telegram")
        print()

        token = input("Paste your Telegram bot token (Enter to skip): ").strip()
        if token:
            chat_id = input("Paste your Telegram chat ID: ").strip()
            if chat_id:
                new_env["TELEGRAM_BOT_TOKEN"] = token
                new_env["TELEGRAM_CHAT_ID"] = chat_id

    if new_runtime:
        cfg_path = Path(getattr(config, "model_config_path", "") or (Path.cwd() / "macgent_config.json"))
        _update_runtime_config(cfg_path, new_runtime)
        print(f"\nSaved runtime config to {cfg_path}")

    if new_env:
        _update_env(env_path, new_env)
        print(f"Saved Telegram settings to {env_path}")
    elif not new_runtime:
        print("\n(Skipped — you can add TELEGRAM_* to .env later)")

    if new_runtime or new_env:
        from macgent.config import Config
        config = Config.from_env()

    print()
    return config


def _setup_workspace(workspace_dir: str):
    """Copy missing base template files from macgent/workspace/ → workspace/.

    Only copies files that don't exist yet — never overwrites the agent's edits.
    Base templates live in macgent/workspace/ (committed, read-only at runtime).
    The runtime workspace lives in workspace/ (agent writes here).
    """
    base_dir = Path(__file__).parent / "workspace"
    dest_dir = Path(workspace_dir)

    if not base_dir.exists():
        return

    for src in base_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(base_dir)
        dst = dest_dir / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Mirror core skill references into workspace for on-demand reading by the agent.
    core_skills_dir = Path(__file__).parent / "skills"
    skills_dest = dest_dir / "skills" / "core"
    if core_skills_dir.exists():
        for src in core_skills_dir.glob("*.md"):
            dst = skills_dest / src.name
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)


def _setup_logging(log_file: str, debug: bool = False):
    """Configure logging with INFO by default and DEBUG only when requested."""
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Console: always INFO+ so normal runs stay readable.
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # File: INFO+ by default, DEBUG+ only when --debug is passed.
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG if debug else logging.INFO)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    # Suppress noisy third-party HTTP loggers unless debugging.
    if not debug:
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _resolve_daily_log_path(log_file: str) -> str:
    """Return a date-stamped log path, e.g. logs/macgent-YYYY-MM-DD.log."""
    path = Path(log_file)
    day = date.today().strftime("%Y-%m-%d")
    if day in path.stem:
        return str(path)
    if path.suffix:
        return str(path.with_name(f"{path.stem}-{day}{path.suffix}"))
    return str(path.with_name(f"{path.name}-{day}"))


def main():
    from dotenv import load_dotenv, find_dotenv
    dotenv_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path)
    env_file = Path(dotenv_path) if dotenv_path else Path(".env")

    from macgent.config import Config, MACGENT_DIR
    config = Config.from_env()
    config.log_file = _resolve_daily_log_path(config.log_file)

    # Interactive setup wizard for first-run config (name/workspace/telegram)
    config = _run_setup_wizard(config, env_file)

    # Ensure data directories exist
    MACGENT_DIR.mkdir(parents=True, exist_ok=True)
    Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

    # Copy any missing base template files to the runtime workspace (never overwrites)
    _setup_workspace(config.workspace_dir)

    raw_args = sys.argv[1:]
    debug_enabled = ("--debug" in raw_args) or (config.get_logging_level() == "DEBUG")
    cli_args = [a for a in raw_args if a != "--debug"]

    # Set up logging (file + console) now that we know the log path
    _setup_logging(config.log_file, debug=debug_enabled)

    if not config.reasoning_api_key:
        print("ERROR: Set OPENROUTER_API_KEY (or REASONING_API_KEY) in .env file")
        sys.exit(1)

    # Detect legacy mode: if first arg isn't a known subcommand, run worker Agent directly
    SUBCOMMANDS = {"task", "daemon", "status", "log", "answer", "soul", "-h", "--help"}
    if len(cli_args) > 0 and cli_args[0] not in SUBCOMMANDS:
        task_text = " ".join(cli_args)
        from macgent.memory import MemoryManager
        from macgent.agent import Agent
        memory = MemoryManager(config)
        agent = Agent(config, db=None, memory=memory, task_description=task_text)
        state = agent.run(task_text)
        print(f"\n{'='*60}")
        print(f"Task: {task_text}")
        print(f"{'='*60}")
        print(f"Status: {state.status}")
        if state.steps:
            last = state.steps[-1]
            if last.action.type == "done":
                print(f"Summary: {last.action.params.get('summary', 'completed')}")
            elif last.action_result:
                print(f"Result: {str(last.action_result)[:500]}")
        return

    import argparse
    parser = argparse.ArgumentParser(prog="macgent", description="macOS automation multi-agent system")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging (includes LLM prompts/responses).")
    sub = parser.add_subparsers(dest="command")

    # macgent daemon — start heartbeat loop
    daemon_p = sub.add_parser("daemon", help="Start the manager heartbeat daemon")
    daemon_p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    daemon_p.add_argument("--interval", type=int, default=None, help="Heartbeat interval in seconds")

    # macgent log — show agent activity
    log_p = sub.add_parser("log", help="Show agent activity log")
    log_p.add_argument("-n", type=int, default=20, help="Number of entries")

    # macgent soul edit <role> — open soul file in editor
    soul_p = sub.add_parser("soul", help="View or edit soul files")
    soul_p.add_argument("action", choices=["edit", "show"], help="Action")
    soul_p.add_argument("role", choices=["agent"], help="Role")

    args = parser.parse_args(raw_args)

    if args.command is None:
        print("No subcommand provided. Starting daemon mode (continuous).")
        _run_daemon(config, config.daemon_interval, once=False)
        return

    if args.command == "daemon":
        interval = args.interval or config.daemon_interval
        _run_daemon(config, interval, once=args.once)

    elif args.command == "log":
        _show_log(config, args.n)

    elif args.command == "soul":
        _soul_command(config, args.action, args.role)


def _run_daemon(config, interval: int, once: bool = False):
    """Run the unified manager daemon with Telegram bot integration."""
    import asyncio
    asyncio.run(_run_daemon_async(config, interval, once))


async def _run_daemon_async(config, interval: int, once: bool):
    """Async daemon that runs Telegram polling alongside the sync heartbeat loop."""
    import asyncio


    print(f"macgent daemon started (interval={interval}s, Ctrl+C to stop)")

    # Start Telegram polling if configured
    telegram_task = None
    if config.telegram_bot_token:
        from macgent.telegram_bot import TelegramBot
        bot = TelegramBot(config)
        print("✓ Telegram bot enabled — listening on @MacGentBot")
        telegram_task = asyncio.create_task(bot.run_polling())
    else:
        print("(Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)")

    # Run the sync daemon loop in a thread pool
    # Note: DB objects must be created in the executor thread, not passed from main thread
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _sync_daemon_loop, config, interval, once
        )
    finally:
        if telegram_task:
            telegram_task.cancel()
            try:
                await telegram_task
            except asyncio.CancelledError:
                pass


def _sync_daemon_loop(config, interval, once):
    """Synchronous daemon loop (runs in thread pool while Telegram polls in async)."""
    import time
    from macgent.memory import MemoryManager
    from macgent.roles.manager import ManagerRole

    memory = MemoryManager(config)
    manager = ManagerRole(config, None, memory)

    try:
        while True:
            manager.tick()

            if once:
                break

            # Sleep with early wake support for active Telegram messages.
            sleep_start = time.time()
            while True:
                elapsed = time.time() - sleep_start
                if elapsed >= interval:
                    break  # Normal wake by interval
                if manager.should_wake_early():
                    print("⚡ Waking early due to external notification!")
                    break  # Woken by external signal
                time.sleep(0.5)  # Check every 500ms for wake signals
    except KeyboardInterrupt:
        print("\nDaemon stopped.")


def _show_log(config, n: int):
    """Show recent agent activity."""
    from pathlib import Path

    path = Path(config.log_file)
    if not path.exists():
        print("No log file found.")
        return
    lines = path.read_text().splitlines()
    if not lines:
        print("No log entries.")
        return
    for line in lines[-max(1, n):]:
        print(line)


def _soul_command(config, action: str, role: str):
    """View or edit soul files (workspace/{role}/SOUL.md)."""
    from pathlib import Path
    soul_path = Path(config.workspace_dir) / role / "SOUL.md"
    if action == "show":
        if soul_path.exists():
            print(soul_path.read_text())
        else:
            print(f"No soul file for {role} at {soul_path}")
    elif action == "edit":
        import os
        editor = os.getenv("EDITOR", "nano")
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        os.execvp(editor, [editor, str(soul_path)])



def _print_result(state):
    """Print single-agent result."""
    print(f"\n{'='*60}")
    print(f"Task: {state.task}")
    print(f"Status: {state.status}")
    print(f"Steps: {len(state.steps)}")
    if state.steps:
        last = state.steps[-1]
        print(f"Last action: {last.action.type} {last.action.params}")


if __name__ == "__main__":
    main()
