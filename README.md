# macgent

**A multi-agent macOS automation system with memory, soul, and intelligent task management.**

macgent is a system of cooperating AI agents that can automate your Mac: browse the web, read/send emails, manage calendars, control applications, and learn from experience.

> "The soul gives purpose. Memory gives wisdom. Skills give power."

## Quick Start

### Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/macgent
cd macgent

# Install dependencies (requires Python 3.12+)
uv sync

# Set up environment
cp .env.example .env
# Edit .env and add your API keys (see below)
```

### Configuration

Create a `.env` file and a `macgent_config.json` routing file:

```bash
cp .env.example .env
cp macgent_config.json.example macgent_config.json
```

In `.env`, set API keys and `MACGENT_CONFIG_PATH`. In `macgent_config.json`, set primary/fallback text and vision model aliases.

### First Task

Run macgent with a simple task:

```bash
uv run macgent 'Go to news.ycombinator.com and tell me the top 3 stories'
```

Or run the examples:

```bash
bash examples/web_search_test.sh
bash examples/booking_hotels.sh
bash examples/google_sheets.sh
bash examples/mail_test.sh
```

## How It Works

macgent has **three coordinating roles**:

### 🧠 Manager
- Monitors email for actionable items
- Classifies tasks by priority
- Creates task entries
- Checks on stuck tasks
- Escalates to you when needed

### 🔧 Worker
- Executes tasks using **browser automation**
- Interacts with web applications
- Reads/sends emails
- Accesses calendars
- Reports progress and results

### ✓ Stakeholder
- Reviews Worker's plan before execution
- Checks quality of completed work
- Approves or requests changes
- Escalates ambiguous or impossible tasks

These agents have **souls** (character definitions) and **memory** (learning from past tasks), making them more effective over time.

## Core Concepts

### Skill System

macgent uses two skill tiers:
- **Core skills** (`macgent/skills/*.md`) are always loaded and must map to runtime actions.
- **Learned skills** (`workspace/skills/*.md`) are environment-specific markdown references.

Load order is always core first, then learned skills.

### Skills

Available capabilities agents can use:

- **[Browser Automation](./macgent/skills/browser_automation.md)** — Navigate, click, type, scroll in Safari
- **[Agent Browser](./macgent/skills/agent_browser.md)** — Primary browser-task delegation runtime
- **[Email Operations](./macgent/skills/email_operations.md)** — Read/send emails via Mail app
- **[Calendar](./macgent/skills/calendar_operations.md)** — Read events and check availability
- **[iMessages](./macgent/skills/messages.md)** — Send/read iMessages
- **[AppleScript](./macgent/skills/applescript.md)** — Control macOS applications
- **[JavaScript](./macgent/skills/javascript.md)** — Extract data from web pages
- **[Evaluate Image](./macgent/skills/evaluate_image.md)** — Vision fallback for non-multimodal text models
- **[Brave Search](./macgent/skills/brave_search.md)** — Fast API-based web search without browser navigation

See [skills/README.md](./skills/README.md) for detailed documentation.

Skill architecture and runtime mapping are documented in [docs/PROJECT_SETUP.md](./docs/PROJECT_SETUP.md).

### Souls

Each agent has a **soul** — a character definition that guides behavior. Souls are markdown files that define:
- Who the agent is
- What they're responsible for
- How they approach problems
- Rules and constraints

Primary soul files:
- `workspace/manager/soul.md`
- `workspace/worker/soul.md`

### Memory

Memory is file-based and always injected into prompts:
- `workspace/core_memory.md` (global memory contract)
- `workspace/memory/daily/memory-YYYY-MM-DD.md` (recent logs, today+yesterday by default)
- `workspace/memory/semantic_memories.jsonl` (semantic lessons, top-N recalled per task)

## Usage Modes

### Single-Agent Mode (Quick Tasks)

For quick one-off tasks, run the agent directly:

```bash
uv run macgent 'Search for Python tutorials and list the top 5'
```

The agent:
1. Takes a screenshot
2. Reasons about what to do
3. Executes actions (click, type, navigate)
4. Observes results
5. Repeats until done or max steps reached

### Task Mode (With Review)

For important tasks, use the task system with stakeholder review:

```bash
uv run macgent task 'Read my recent emails and summarize them'
```

Workflow:
1. Worker creates a plan
2. Stakeholder reviews the plan
3. Worker executes after approval
4. Stakeholder reviews results
5. Worker makes changes if needed (up to 3 rounds)
6. Task marked complete or escalated

### Daemon Mode (Background Automation)

Run a persistent manager that monitors your system:

```bash
uv run macgent daemon
```

The daemon:
- ✉️ Monitors email every minute
- 📋 Creates tasks for important items
- 🤖 Manages the task board
- 🔔 Uses Telegram for notifications
- 💬 Accepts commands from Telegram

Start daemon with specific interval:

```bash
uv run macgent daemon --interval 60  # Check every 60 seconds
```

Or test one cycle without looping:

```bash
uv run macgent daemon --once
```

## Configuration

### Environment Variables

See `.env.example` for current options. Model routing is defined in `macgent_config.json` (primary + fallback chains for text and vision).

### Soul Customization

Edit how agents behave:

```bash
uv run macgent soul edit worker    # How Worker executes tasks
uv run macgent soul edit manager   # How Manager monitors email
uv run macgent soul edit stakeholder  # How Stakeholder reviews
```

These files are the source of truth:
- `workspace/manager/soul.md`
- `workspace/worker/soul.md`

## Examples

Ready-to-run examples demonstrating different capabilities:


### Hotel Booking
```bash
bash examples/booking_hotels.sh
```
Agent navigates Booking.com, searches for hotels near Basel.

### Google Sheets
```bash
bash examples/google_sheets.sh
```
Agent creates spreadsheet, enters data.

### Email
```bash
bash examples/mail_test.sh
```
Agent reads emails, sends test message.

## Monitoring

### View Task Status

```bash
uv run macgent status
```

Shows all tasks with status indicators:
- ` ` = pending
- `>` = in progress
- `R` = review
- `+` = completed
- `!` = failed
- `^` = escalated

### View Activity Log

```bash
uv run macgent log -n 20
```

Shows recent agent actions and turns.

### Inspect Results

After a task completes:

```bash
uv run macgent status
# Look for task details
```

## Common Tasks

### Automate a Web Form

```bash
uv run macgent 'Go to example.com. Fill in the form with name="John", email="john@example.com", submit.'
```

### Search and Extract Data

```bash
uv run macgent 'Go to weather.com, search for "Basel Switzerland", get the 5-day forecast.'
```

### Email Automation

```bash
uv run macgent task 'Read my recent emails from this week and forward the important ones to my boss.'
```

### Multi-Step Workflows

```bash
uv run macgent task 'Check the weather for next week, check my calendar availability, and email me a summary.'
```

## Architecture

```
macgent/
├── actions/          # Action executors (click, type, navigate)
├── perception/       # Observation generators (screenshots, DOM extraction)
├── reasoning/        # LLM integration and decision-making
├── roles/            # Manager, Worker, Stakeholder agent implementations
├── prompts/          # System prompts and context builders
├── memory.py         # File-based memory context + semantic recall
├── db.py             # Database (messages, monitor state, logs)
└── agent.py          # Single-agent orchestrator

skills/              # Documentation of available skills
docs/                # Project architecture and setup docs
workspace/           # Runtime soul + memory files copied from macgent/workspace templates
examples/            # Example scripts to run
```

## Troubleshooting

### "ERROR: Set REASONING_API_KEY in .env file"
Add your LLM API key to `.env` and ensure it's loaded.

### Agent seems stuck
- Press Ctrl+C to stop the agent
- Check `uv run macgent log` to see what it was doing
- Review the soul if behavior is unexpected
- Run a simpler task to test

### Browser actions not working
- Ensure Safari is the default browser
- If using another browser, see [Browser Automation](./skills/browser_automation.md)
- Close popups manually if agent gets stuck
- Check that interactive elements are visible on screen

### Semantic recall disabled
Install optional dependency:
```bash
uv pip install fastembed
```

### Telegram notifications not working
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

## Development

### Adding a New Skill

1. Implement the action in `macgent/actions/`
2. Document it in `skills/skill_name.md`
3. Add to Worker soul
4. Test with an example script

### Customizing an Agent's Soul

Edit the soul file and the agent will automatically use the new behavior:

```bash
uv run macgent soul edit worker
# Make changes, save file
# Next task will use the new soul
```

### Debugging Agent Decisions

Enable verbose logging:

```bash
LOGLEVEL=DEBUG uv run macgent 'Your task'
```

### Running Tests

```bash
uv run pytest tests/
```

## Data Privacy

- All data is stored locally (`~/.macgent/`)
- No cloud syncing of tasks or memories
- API calls go to your configured LLM provider
- Safari history/cookies not accessed
- Email and calendar integration use local APIs

## Limitations

- **Requires Safari** for browser automation (not Chrome/Firefox yet)
- **macOS only** (uses native APIs)
- **No login automation** by default (can be customized in soul)
- **Single-page apps** take more steps (SPAs don't reload visually)
- **Error recovery** is manual (agent doesn't retry internally)

## Future Roadmap

- [ ] ChromeDriver support (for other browsers)
- [ ] Memory pruning (forgetting old memories)
- [ ] Explicit memory queries (agents ask what they know)
- [ ] Cross-agent memory sharing
- [ ] Mobile device control
- [ ] Voice commands for tasks
- [ ] Web UI for task management

## License

MIT License - See LICENSE file.

## Contributing

Contributions welcome! Please:

1. Fork the repo
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## Support

- 📚 **Guides**: See [docs/](./docs/) for in-depth documentation
- 🛠️ **Skills**: Check [skills/](./skills/) for what agents can do
- 💡 **Examples**: Run the [examples/](./examples/) to see it in action
- 🐛 **Issues**: Report bugs on GitHub

## See Also

- [macgent/workspace/core_memory.md](./macgent/workspace/core_memory.md) — Core memory contract template
- [skills/README.md](./skills/README.md) — Complete skill reference
- [TELEGRAM_BOT.md](./TELEGRAM_BOT.md) — Using the Telegram integration
