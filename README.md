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

Routing structure is:
- `providers`: API endpoint + auth env var (`api_key_env`)
- `offers`: model aliases per modality (`text` / `vision`) mapped to a provider + model id
- `routes`: `primary` + ordered `fallbacks` aliases for each modality

Minimal pattern:
```json
{
  "providers": {
    "openrouter": {"api_base": "https://openrouter.ai/api/v1", "api_type": "openai", "api_key_env": "OPENROUTER_API_KEY"}
  },
  "offers": {
    "text": {"fast_text": {"provider": "openrouter", "model": "qwen/qwen3-coder:free"}},
    "vision": {"fast_vision": {"provider": "openrouter", "model": "nvidia/nemotron-nano-12b-v2-vl:free"}}
  },
  "routes": {
    "text": {"primary": "fast_text", "fallbacks": []},
    "vision": {"primary": "fast_vision", "fallbacks": []}
  }
}
```

### First Task

Run first-time setup + bootstrap heartbeat:

```bash
uv run macgent
```

The setup wizard configures Telegram (if needed), copies templates from `macgent/workspace/`, then runs one startup heartbeat (`bootstrap.md` on first run).

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

macgent runs as a **single Agent** with a file-based soul, memory, and skill system. The daemon wakes the agent on a schedule or on Telegram messages. The agent reads its markdown instructions, calls an LLM, executes returned actions, and sleeps until next time.

---

## System Flow

### Scenario 1 — First-Time Boot (Bootstrap)

On the very first run, `workspace/agent/IDENTITY.md` does not exist and `workspace/agent/BOOTSTRAP.md` does. The agent detects this and enters bootstrap mode.

```
startup
  └─ _is_bootstrapped() → False
       ├─ system prompt  ←  workspace/agent/SOUL.md  (only, no memory context)
       └─ user prompt    ←  workspace/agent/BOOTSTRAP.md
            │
            ▼
       LLM multi-turn loop (up to 15 turns)
            │
            ├─ LLM returns JSON actions, executed one by one:
            │    • send_telegram  — introduces itself, asks CEO 3 questions
            │    • file_write     — creates workspace/agent/USER.md (fields marked "unknown (asked)")
            │    • file_write     — creates workspace/agent/IDENTITY.md  ← marks bootstrap complete
            │    • file_delete    — deletes workspace/agent/BOOTSTRAP.md
            │
            └─ LLM responds HEARTBEAT_OK → bootstrap cycle ends
```

**Files loaded into context during bootstrap:**

| File | Purpose |
|------|---------|
| `workspace/agent/SOUL.md` | System prompt — personality, workspace layout, skill index |
| `workspace/agent/BOOTSTRAP.md` | User prompt — step-by-step first-run instructions |

> Bootstrap is intentionally minimal: no memory, no identity, no skills pre-loaded. The LLM only sees its soul and its one-time setup instructions.

**Bootstrap completes when:**
- `workspace/agent/IDENTITY.md` exists
- `workspace/agent/BOOTSTRAP.md` is deleted
- The next `tick()` sees `_is_bootstrapped() → True` and switches to the normal heartbeat

---

### Scenario 2 — Passive Heartbeat

After bootstrap the daemon wakes every `daemon_interval` seconds (default: 1800 s / 30 min). The agent runs a heartbeat check against the Notion board and any pending messages.

```
scheduler wake (every 30 min by default)
  └─ _is_bootstrapped() → True
  └─ no pending Telegram message
       │
       ├─ system prompt  ←  memory.build_context("agent")
       │    Assembled in this order, separated by markdown headings:
       │
       │      # Soul
       │      workspace/agent/SOUL.md
       │
       │      # Identity
       │      workspace/agent/IDENTITY.md
       │
       │      # Core Memory
       │      workspace/agent/memory/CORE_MEMORY.md
       │
       │      # Role Memory
       │      workspace/agent/memory/LONGTERM_MEMORY.md
       │
       │      # Recent Memory (last N days)
       │      workspace/memory/<YYYY-MM-DD>_MEMORY.md  (today + yesterday by default)
       │
       │      # Relevant Memory Chunks (top-K)
       │      Semantically recalled entries from semantic_memories.jsonl
       │
       └─ user prompt    ←  workspace/agent/HEARTBEAT.md
            │
            ▼
       LLM multi-turn loop (up to 15 turns)
            │
            ├─ LLM returns JSON action(s) → Python executes each:
            │    {"actions": [
            │      {"type": "notion_query", "params": {...}},
            │      {"type": "send_telegram", "params": {"text": "Blocked: task X needs your input"}}
            │    ]}
            │    Results fed back: "Action results: [...]\nContinue or respond HEARTBEAT_OK."
            │
            └─ LLM responds HEARTBEAT_OK → tick ends cleanly
```

**Files loaded into context during a heartbeat:**

| File | Section in prompt | Description |
|------|-------------------|-------------|
| `workspace/agent/SOUL.md` | Soul | Personality, workspace layout, on-demand skill index |
| `workspace/agent/IDENTITY.md` | Identity | Agent's name, style, communication approach |
| `workspace/agent/memory/CORE_MEMORY.md` | Core Memory | Memory policy — how to read/write memory |
| `workspace/agent/memory/LONGTERM_MEMORY.md` | Role Memory | Curated long-term lessons, distilled nightly |
| `workspace/memory/<YYYY-MM-DD>_MEMORY.md` | Recent Memory | Rolling daily log for the last N days |
| `workspace/memory/semantic_memories.jsonl` | Relevant Chunks | Top-K entries recalled by semantic/lexical similarity to the task |
| `workspace/agent/HEARTBEAT.md` | User prompt | Checklist: what to inspect and how to respond |

> **Skills are not pre-loaded.** `SOUL.md` lists skill file paths. The agent reads them on-demand with a `file_read` action when it needs a specific action's schema (e.g., `workspace/skills/core/brave_search.md`).

---

### Scenario 3 — Active Messaging (Telegram Wake)

When you send a message via Telegram, the bot enqueues it in an in-memory FIFO and fires a wake signal. The sleeping daemon detects this within 500 ms and wakes early.

```
you → Telegram → TelegramBot.handle_message()
  └─ message_bus.enqueue_message("ceo", "agent", task_id, text)
  └─ message_bus.request_wake()
       │
       ▼  daemon sleep-poll fires (checks every 500 ms)
agent tick (early wake)
  └─ should_wake_early() → True → clear_wake_request()
  └─ ceo_message = message_bus.dequeue_message("agent", from_role="ceo")
       │
       ├─ system prompt  ←  memory.build_context("agent")   (same full context as heartbeat)
       │
       └─ user prompt    ←  built inline:
            "Process this CEO message now. Execute actions as needed.
             When fully handled, respond HEARTBEAT_OK.
             ## CEO Message
             {your message text}"
            │
            ▼
       LLM multi-turn loop (up to 15 turns)
            │
            ├─ LLM may execute any combination of actions:
            │    • notion_create   — create a new task from your request
            │    • notion_update   — unblock a waiting task
            │    • send_telegram   — reply to you with confirmation or a question
            │    • (any other registered action)
            │
            └─ LLM responds HEARTBEAT_OK → active cycle ends

  then (always, regardless of active/passive):

worker.tick()
  └─ notion_query → find first task with status containing "ready"
       └─ run_task(task)
            └─ Agent.run(task_description + notion page_id)
                 │
                 ├─ macOS task? (keywords: email / mail / calendar / imessage / message)
                 │    └─ _run_macos_direct_loop()
                 │         Step loop (up to max_steps, default 30):
                 │           observe → think (LLM) → act → observe
                 │         Terminal: action.type == "done" or "fail"
                 │
                 └─ Web / other task?
                      └─ _run_browser_task_delegate()
                           Dispatches a single "browser_task" action
                           Browser agent runs its own internal loop
                           Terminal: payload["solved"] == True / False
```

---

## LLM Call Structure

Every call follows the same pattern:

```
SYSTEM:
  # Soul
  <workspace/agent/SOUL.md content>

  ---

  # Identity
  <workspace/agent/IDENTITY.md content>

  ---

  # Core Memory
  <workspace/agent/memory/CORE_MEMORY.md content>

  ---

  # Role Memory          (if non-empty)
  <LONGTERM_MEMORY.md>

  ---

  # Recent Memory (last N days)   (if non-empty)
  <YYYY-MM-DD_MEMORY.md + previous day ...>

  ---

  # Relevant Memory Chunks (top-K)   (if task_description given)
  - [lesson] ...recalled entry...

USER:
  <HEARTBEAT.md content>
  — or —
  <BOOTSTRAP.md content>
  — or —
  "Process this CEO message: ..."
  — or —
  <task description + notion page_id>

[multi-turn]
  ASSISTANT: {"actions": [...]}
  USER:      "Action results: [...]\nContinue or respond HEARTBEAT_OK."
  ASSISTANT: HEARTBEAT_OK
```

The system prompt is **rebuilt fresh on every tick** — nothing is cached between cycles. The memory sections are non-empty only when the corresponding files exist and have content.

---

## "Done" Signal Reference

| Context | Signal | Code location |
|---------|--------|---------------|
| Agent heartbeat / active message | LLM text contains `HEARTBEAT_OK` | `manager.py` — turn loop |
| Worker macOS step loop | `action.type == "done"` | `agent.py` — `_run_macos_direct_loop` |
| Worker macOS step loop | `action.type == "fail"` | `agent.py` — `_run_macos_direct_loop` |
| Worker macOS step loop | Same action repeated 3× | `agent.py` — stuck detection |
| Worker macOS step loop | `max_steps` exhausted | `agent.py` — loop exit |
| Worker browser task | `payload["solved"] == True` | `agent.py` — `_run_browser_task_delegate` |
| Agent heartbeat turn limit | 15 turns without `HEARTBEAT_OK` | `manager.py` — `MAX_TURNS = 15` |

**Summary:** The orchestrator (agent/heartbeat loop) signals completion via the plain-text sentinel `HEARTBEAT_OK`. The task execution loop signals completion via structured JSON action types (`done` / `fail`). There is no other magic keyword.

---

The agent has a **soul** (character definition) and **memory** (file-based, grows over time), making it more effective with every interaction.

## Core Concepts

### Skill System

macgent uses two skill tiers:
- **Core skills** (`macgent/skills/*.md`) are always loaded and must map to runtime actions.
- **Learned skills** (`workspace/skills/*.md`) are environment-specific markdown references.

Load order is always core first, then learned skills.

### Skills

Available capabilities agents can use:

- **[Browser Automation](./macgent/skills/browser_automation.md)** — Navigate, click, type, scroll in Safari
- **[Browser Agent](./macgent/skills/browser-agent.md)** — Primary browser-task delegation runtime
- **[Email Operations](./macgent/skills/email_operations.md)** — Read/send emails via Mail app
- **[Calendar](./macgent/skills/calendar_operations.md)** — Read events and check availability
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
