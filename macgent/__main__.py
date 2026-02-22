import sys
import os
import logging


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load .env
    from dotenv import load_dotenv
    load_dotenv()

    from macgent.config import Config
    config = Config.from_env()

    if not config.reasoning_api_key:
        print("ERROR: Set REASONING_API_KEY in .env file")
        print("  cp .env.example .env  # then edit with your keys")
        sys.exit(1)

    # Get task from args
    if len(sys.argv) < 2:
        print("Usage: python -m macgent 'Your task here'")
        print()
        print("Examples:")
        print("  python -m macgent 'Go to example.com and tell me what links are on the page'")
        print("  python -m macgent 'Open Calendar and add event for Sunday: it works omg!'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])

    from macgent.agent import Agent
    agent = Agent(config)
    state = agent.run(task)

    # Summary
    print(f"\n{'='*60}")
    print(f"Task: {state.task}")
    print(f"Status: {state.status}")
    print(f"Steps: {len(state.steps)}")
    if state.steps:
        last = state.steps[-1]
        print(f"Last action: {last.action.type} {last.action.params}")


if __name__ == "__main__":
    main()
