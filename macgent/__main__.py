import sys
import logging


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))

    from macgent.config import Config, MACGENT_DIR
    config = Config.from_env()

    # Ensure data directories exist
    MACGENT_DIR.mkdir(parents=True, exist_ok=True)
    from pathlib import Path
    Path(config.souls_dir).mkdir(parents=True, exist_ok=True)

    if not config.reasoning_api_key:
        print("ERROR: Set REASONING_API_KEY in .env file")
        sys.exit(1)

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

    # macgent task 'do X' — direct CEO task with stakeholder review
    task_p = sub.add_parser("task", help="Create and run a task (with stakeholder review)")
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

    # macgent answer <task_id> 'text' — answer an escalation
    answer_p = sub.add_parser("answer", help="Answer a CEO escalation")
    answer_p.add_argument("task_id", type=int, help="Task ID to answer")
    answer_p.add_argument("text", nargs="+", help="Answer text")

    # macgent soul edit <role> — open soul file in editor
    soul_p = sub.add_parser("soul", help="View or edit soul files")
    soul_p.add_argument("action", choices=["edit", "show"], help="Action")
    soul_p.add_argument("role", choices=["manager", "worker", "stakeholder"], help="Role")

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
        _answer_escalation(config, args.task_id, text)

    elif args.command == "soul":
        _soul_command(config, args.action, args.role)


def _run_task(config, description: str):
    """Create a CEO task and run it through Worker + Stakeholder review."""
    from macgent.db import DB
    from macgent.memory import MemoryManager
    from macgent.roles.worker import WorkerRole
    from macgent.roles.stakeholder import StakeholderRole

    db = DB(config.db_path)
    memory = MemoryManager(config)

    task_id = db.create_task(
        title=description[:80],
        description=description,
        source="ceo",
        priority=2,
    )
    print(f"Created task #{task_id}: {description}")

    worker = WorkerRole(config, db, memory)
    stakeholder = StakeholderRole(config, db, memory)

    # Worker claims and executes with stakeholder ping-pong
    worker.run_task(task_id)

    # Show final state
    task = db.get_task(task_id)
    print(f"\nFinal status: {task['status']}")
    if task.get("result"):
        print(f"Result: {task['result']}")
    if task.get("review_note"):
        print(f"Review: {task['review_note']}")


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
    from macgent.roles.stakeholder import StakeholderRole

    # Create DB connection in this thread (SQLite connections are thread-specific)
    db = DB(config.db_path)
    memory = MemoryManager(config)

    manager = ManagerRole(config, db, memory)
    worker = WorkerRole(config, db, memory)
    stakeholder = StakeholderRole(config, db, memory)

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n{'='*60}")
            print(f"Heartbeat cycle #{cycle}")
            print(f"{'='*60}")

            # 1. Manager checks notifications and manages board
            manager.tick()

            # 2. Stakeholder reviews any tasks in "review" status
            stakeholder.tick()

            # 3. Worker picks and executes pending tasks
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
    """Show tasks from the database."""
    from macgent.db import DB
    db = DB(config.db_path)
    tasks = db.list_tasks()
    if not tasks:
        print("No tasks.")
        return
    for t in tasks:
        status_icon = {
            "pending": " ", "clarifying": "?", "in_progress": ">",
            "review": "R", "completed": "+", "failed": "!", "escalated": "^",
        }.get(t["status"], "?")
        print(f"  [{status_icon}] #{t['id']} (P{t['priority']}) {t['title']}")
        if t.get("review_note"):
            print(f"      Review: {t['review_note'][:80]}")


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


def _answer_escalation(config, task_id: int, text: str):
    """Answer a CEO escalation."""
    from macgent.db import DB
    db = DB(config.db_path)
    task = db.get_task(task_id)
    if not task:
        print(f"Task #{task_id} not found.")
        return
    db.send_message("ceo", "worker", task_id, text)
    db.update_task(task_id, status="pending")
    print(f"Answer sent to task #{task_id}, status set back to pending.")


def _soul_command(config, action: str, role: str):
    """View or edit soul files."""
    from pathlib import Path
    soul_path = Path(config.souls_dir) / f"{role}.md"
    if action == "show":
        if soul_path.exists():
            print(soul_path.read_text())
        else:
            print(f"No soul file for {role} at {soul_path}")
    elif action == "edit":
        import os
        editor = os.getenv("EDITOR", "nano")
        if not soul_path.exists():
            # Create default soul
            from macgent.memory import MemoryManager
            mm = MemoryManager(config)
            mm._ensure_default_souls()
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
