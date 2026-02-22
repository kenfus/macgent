import sys
import logging


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from dotenv import load_dotenv
    load_dotenv()

    from macgent.config import Config
    config = Config.from_env()

    if not config.reasoning_api_key:
        print("ERROR: Set REASONING_API_KEY in .env file")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: uv run macgent 'your task here'")
        print()
        print("Browser examples:")
        print("  uv run macgent 'Go to news.ycombinator.com and tell me the top 5 stories'")
        print("  uv run macgent 'Search Google for Python tutorials and list the first 3 results'")
        print("  uv run macgent 'Go to booking.com, search for hotels in Basel near Novartis Campus'")
        print("  uv run macgent 'Open Google Sheets and create a new spreadsheet with hotel data'")
        print()
        print("macOS examples:")
        print("  uv run macgent 'What events do I have on February 27th?'")
        print("  uv run macgent 'Add a meeting to my calendar for March 1st at 2pm'")
        print("  uv run macgent 'Read my recent emails and summarize them'")
        print("  uv run macgent 'Send a test email to test@example.com'")
        print("  uv run macgent 'Read my iMessages and tell me what is new'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])

    from macgent.agent import Agent
    agent = Agent(config)
    state = agent.run(task)

    print(f"\n{'='*60}")
    print(f"Task: {state.task}")
    print(f"Status: {state.status}")
    print(f"Steps: {len(state.steps)}")
    if state.steps:
        last = state.steps[-1]
        print(f"Last action: {last.action.type} {last.action.params}")


if __name__ == "__main__":
    main()
