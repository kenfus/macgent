import sys
import logging
import shutil
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


def _run_setup_wizard(config, env_path: Path):
    """Interactive terminal setup for missing configuration.

    Only runs if Telegram (or other required config) is not set.
    Never involves the LLM — pure Python/terminal.
    Returns an updated config object.
    """
    needs_setup = not config.telegram_bot_token or not config.telegram_chat_id
    if not needs_setup:
        return config

    print()
    print("=" * 60)
    print("  macgent — first-time setup")
    print("=" * 60)
    print(f"\nWorkspace: {config.workspace_dir}")
    print(f"Log file:  {config.log_file}")

    new_values = {}

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
                new_values["TELEGRAM_BOT_TOKEN"] = token
                new_values["TELEGRAM_CHAT_ID"] = chat_id

    if new_values:
        _update_env(env_path, new_values)
        print(f"\nSaved to {env_path}")
        # Reload env + config
        from dotenv import load_dotenv
        load_dotenv(str(env_path), override=True)
        import os
        for key, val in new_values.items():
            os.environ[key] = val
        from macgent.config import Config
        config = Config.from_env()
    else:
        print("\n(Skipped — you can add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env later)")

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


def _setup_logging(log_file: str):
    """Configure logging: INFO to console, DEBUG to log file (captures everything)."""
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console: INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # File: DEBUG and above (LLM calls, actions, responses, errors)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)


def main():
    from dotenv import load_dotenv, find_dotenv
    dotenv_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path)
    env_file = Path(dotenv_path) if dotenv_path else Path(".env")

    from macgent.config import Config, MACGENT_DIR
    config = Config.from_env()

    # Ensure data directories exist
    MACGENT_DIR.mkdir(parents=True, exist_ok=True)
    Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

    # Copy any missing base template files to the runtime workspace (never overwrites)
    _setup_workspace(config.workspace_dir)

    # Set up logging (file + console) now that we know the log path
    _setup_logging(config.log_file)

    if not config.reasoning_api_key:
        print("ERROR: Set REASONING_API_KEY in .env file")
        sys.exit(1)

    # Interactive setup wizard for missing Telegram config (terminal only, no LLM)
    config = _run_setup_wizard(config, env_file)

    # Detect legacy mode: if first arg isn't a known subcommand, run single agent
    SUBCOMMANDS = {"task", "daemon", "status", "log", "answer", "soul", "-h", "--help"}
    if len(sys.argv) > 1 and sys.argv[1] not in SUBCOMMANDS:
        task_text = " ".join(sys.argv[1:])
        from macgent.agent import Agent
        agent = Agent(config)
        state = agent.run(task_text)
        _print_result(state)
        return

    import argparse
    parser = argparse.ArgumentParser(prog="macgent", description="macOS automation multi-agent system")
    sub = parser.add_subparsers(dest="command")

    # macgent task 'do X' — direct CEO task
    task_p = sub.add_parser("task", help="Create and run a task via Manager + Worker")
    task_p.add_argument("description", nargs="+", help="Task description")

    # macgent daemon — start heartbeat loop
    daemon_p = sub.add_parser("daemon", help="Start the manager heartbeat daemon")
    daemon_p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    daemon_p.add_argument("--interval", type=int, default=None, help="Heartbeat interval in seconds")

    # macgent status — show tasks
    sub.add_parser("status", help="Show tasks from the database")

    # macgent log — show agent activity
    log_p = sub.add_parser("log", help="Show agent activity log")
    log_p.add_argument("-n", type=int, default=20, help="Number of entries")

    # macgent answer <page_id> 'text' — answer a blocked task
    answer_p = sub.add_parser("answer", help="Answer a blocked task")
    answer_p.add_argument("page_id", help="Notion page ID of the blocked task")
    answer_p.add_argument("text", nargs="+", help="Answer text")

    # macgent soul edit <role> — open soul file in editor
    soul_p = sub.add_parser("soul", help="View or edit soul files")
    soul_p.add_argument("action", choices=["edit", "show"], help="Action")
    soul_p.add_argument("role", choices=["manager", "worker"], help="Role")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        print()
        print("Quick start:")
        print("  uv run macgent 'Go to news.ycombinator.com and tell me the top 3 stories'")
        print("  uv run macgent task 'Read my recent emails and summarize them'")
        print("  uv run macgent daemon          # Start the manager heartbeat")
        print("  uv run macgent status           # Show current tasks")
        sys.exit(1)

    if args.command == "task":
        description = " ".join(args.description)
        _run_task(config, description)

    elif args.command == "daemon":
        interval = args.interval or config.daemon_interval
        _run_daemon(config, interval, once=args.once)

    elif args.command == "status":
        _show_status(config)

    elif args.command == "log":
        _show_log(config, args.n)

    elif args.command == "answer":
        text = " ".join(args.text)
        _answer_escalation(config, args.page_id, text)

    elif args.command == "soul":
        _soul_command(config, args.action, args.role)


def _run_task(config, description: str):
    """Create a CEO task and run it through the Worker."""
    from macgent.db import DB
    from macgent.memory import MemoryManager
    from macgent.roles.manager import ManagerRole
    from macgent.roles.worker import WorkerRole
    from macgent.actions import notion_actions

    db = DB(config.db_path)
    memory = MemoryManager(config)

    # Route through manager LLM to create Notion task
    manager = ManagerRole(config, db, memory)
    page_id = manager.handle_new_ceo_task(description)
    if not page_id:
        print("Failed to create task in Notion.")
        return
    print(f"Created task in Notion: {description}")

    # Get the created task
    task = notion_actions.notion_get(config.notion_token, page_id)
    if not task:
        print("Could not retrieve created task.")
        return

    # Run immediately via worker
    worker = WorkerRole(config, db, memory)
    worker.run_task(task)

    # Show final status from Notion
    task = notion_actions.notion_get(config.notion_token, page_id)
    if task:
        print(f"\nFinal status: {task.get('Status', '?')}")
        notes = task.get("Notes", "")
        if notes:
            print(f"Notes: {notes}")


def _run_daemon(config, interval: int, once: bool = False):
    """Run the unified manager daemon with Telegram bot integration."""
    import asyncio
    asyncio.run(_run_daemon_async(config, interval, once))


async def _run_daemon_async(config, interval: int, once: bool):
    """Async daemon that runs Telegram polling alongside the sync heartbeat loop."""
    import asyncio
    from macgent.db import DB


    print(f"macgent daemon started (interval={interval}s, Ctrl+C to stop)")

    # Start Telegram polling if configured
    telegram_task = None
    if config.telegram_bot_token:
        from macgent.telegram_bot import TelegramBot
        # Telegram bot needs its own DB connection (different thread)
        tg_db = DB(config.db_path)
        bot = TelegramBot(config, tg_db)
        print("✓ Telegram bot enabled — listening on @MacGentBot")
        telegram_task = asyncio.create_task(bot.run_polling())
    else:
        print("(Telegram not configured — set TELEGRAM_BOT_TOKEN to enable)")

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
    from macgent.db import DB
    from macgent.memory import MemoryManager
    from macgent.roles.manager import ManagerRole
    from macgent.roles.worker import WorkerRole

    # Create DB connection in this thread (SQLite connections are thread-specific)
    db = DB(config.db_path)
    memory = MemoryManager(config)

    # Embed recent daily memory logs on startup
    try:
        memory.embed_past_logs(db, days=3)
    except Exception as e:
        import logging
        logging.getLogger("macgent").warning(f"embed_past_logs failed: {e}")

    manager = ManagerRole(config, db, memory)
    worker = WorkerRole(config, db, memory)

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n{'='*60}")
            print(f"Heartbeat cycle #{cycle}")
            print(f"{'='*60}")

            # 1. Manager: passive heartbeat check
            #    Returns True if something actionable happened, False = HEARTBEAT_OK
            active = manager.tick()

            # 2. Worker: always check for pending tasks regardless of manager result
            #    (there may be tasks pending from before this cycle)
            worker.tick()

            if once:
                print("\n--once flag set, exiting after one cycle.")
                break

            # Sleep with early wake support for passive notifications (Telegram, Slack, etc.)
            print(f"\nSleeping {interval}s until next heartbeat (or until external wake signal)...")
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


def _show_status(config):
    """Show tasks from the Notion board."""
    from macgent.actions import notion_actions

    tasks = notion_actions.notion_query(config.notion_token, config.notion_database_id)
    if not tasks:
        print("No tasks on the Notion board.")
        return
    for t in tasks:
        # Find title, status, priority from whatever property names exist
        title = ""
        status = ""
        priority = ""
        notes = ""
        for key, val in t.items():
            if key in ("Task Name", "Name", "Title") and val:
                title = val
            if key == "Status" and val:
                status = val
            if key == "Priority" and val:
                priority = val
            if key == "Notes" and val:
                notes = val
        print(f"  [{status or '?'}] ({priority or '?'}) {title or t.get('page_id', '?')[:20]}")
        if notes:
            print(f"      Notes: {notes[:80]}")


def _show_log(config, n: int):
    """Show recent agent activity."""
    from macgent.db import DB
    db = DB(config.db_path)
    entries = db.get_log(limit=n)
    if not entries:
        print("No log entries.")
        return
    for e in entries:
        print(f"  [{e['created_at']}] {e['role']:12s} {e['action']:16s} {(e.get('detail') or '')[:60]}")


def _answer_escalation(config, page_id: str, text: str):
    """Answer a blocked task via CLI."""
    from macgent.db import DB
    from macgent.actions import notion_actions

    task = notion_actions.notion_get(config.notion_token, page_id)
    if not task:
        print(f"Task {page_id} not found in Notion.")
        return

    db = DB(config.db_path)
    db.send_message("ceo", "manager", page_id, text)

    # Find title
    title = ""
    for key in ("Task Name", "Name", "Title"):
        if key in task and task[key]:
            title = task[key]
            break

    print(f"Answer queued for '{title or page_id}'. Manager will process it on next heartbeat.")


def _soul_command(config, action: str, role: str):
    """View or edit soul files (workspace/{role}/soul.md)."""
    from pathlib import Path
    soul_path = Path(config.workspace_dir) / role / "soul.md"
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
