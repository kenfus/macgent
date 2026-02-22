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

    # macgent telegram — run Telegram bot polling
    telegram_p = sub.add_parser("telegram", help="Run Telegram bot polling")
    telegram_p.add_argument("--once", action="store_true", help="Process one batch of messages then exit")

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

    elif args.command == "telegram":
        _run_telegram(config, once=args.once)


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
    """Run the manager heartbeat daemon."""
    import time
    from macgent.db import DB
    from macgent.memory import MemoryManager
    from macgent.roles.manager import ManagerRole
    from macgent.roles.worker import WorkerRole
    from macgent.roles.stakeholder import StakeholderRole

    db = DB(config.db_path)
    memory = MemoryManager(config)

    manager = ManagerRole(config, db, memory)
    worker = WorkerRole(config, db, memory)
    stakeholder = StakeholderRole(config, db, memory)

    print(f"macgent daemon started (interval={interval}s, Ctrl+C to stop)")
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

            print(f"\nSleeping {interval}s until next heartbeat...")
            time.sleep(interval)
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


def _run_telegram(config, once: bool = False):
    """Run Telegram bot polling."""
    import asyncio
    from macgent.db import DB
    from macgent.telegram_bot import TelegramBot

    if not config.telegram_bot_token:
        print("ERROR: Set TELEGRAM_BOT_TOKEN in .env file")
        sys.exit(1)

    db = DB(config.db_path)
    bot = TelegramBot(config, db)

    if once:
        # Run one batch of updates then exit
        async def fetch_once():
            updates = await bot.get_updates(timeout=5)
            for update in updates:
                bot.offset = update["update_id"] + 1
                if "message" in update:
                    await bot.process_message(update["message"])
                elif "callback_query" in update:
                    await bot.handle_callback_query(update["callback_query"])
            print(f"Processed {len(updates)} updates")

        asyncio.run(fetch_once())
    else:
        # Run continuous polling
        try:
            asyncio.run(bot.run_polling())
        except KeyboardInterrupt:
            print("\nTelegram bot stopped.")


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
