# Project Setup: Skills + Model Routing

This document is the source of truth for how macgent is structured and extended.

Model routing is configured in `macgent_config.json` (copy from `macgent_config.json.example`).

## Architecture Overview

macgent has two skill classes with different lifecycle rules:

1. **Core skills**
- Location: `macgent/skills/*.md`
- Load behavior: always loaded first by `MemoryManager.load_skills()`
- Requirement: must map to real runtime actions/functions in Python
- Purpose: foundational capabilities needed every run (browser, macOS, communication, files, memory)

2. **Learned skills**
- Location: `workspace/skills/*.md`
- Load behavior: loaded after core skills on every run
- Requirement: markdown-only guidance (no required Python module)
- Purpose: environment/user-specific operating knowledge (for example Notion schema)

Load precedence is always: **core -> learned**.

## Memory Context Contract

Memory is file-based (no database-backed memory retrieval). On every context build, the agent gets:

1. `workspace/<role>/identity.md` (with `IDENTITY.md` backward-compatible fallback)
2. `workspace/<role>/soul.md`
3. Core + learned skills
4. `workspace/core_memory.md`
5. `workspace/<role>/MEMORY.md` (if present)
6. Recent daily memory logs (`workspace/memory/daily/`, today + yesterday by default)
7. Top-N relevant chunks from `workspace/memory/semantic_memories.jsonl` for the current task

This full context is attached to every LLM call through role/system prompt construction.

## First-Run Startup Flow

Running `uv run macgent` on first run prompts for:

1. Agent name (`MACGENT_NAME`)
2. Workspace path (`MACGENT_WORKSPACE_DIR`, suggested: `<repo>/workspace`)

Then startup copies all template files from `macgent/workspace/` into the selected workspace (copy-if-missing), including:

- `core_memory.md`
- `manager/bootstrap.md`
- `manager/soul.md`
- `manager/identity.md`
- `manager/heartbeat.md`
- `worker/soul.md`
- `worker/identity.md`

After template copy, Manager bootstrap starts from `manager/bootstrap.md`.

## Manager Runtime Rule

Manager Python code should stay thin:
- It loads context and `manager/bootstrap.md` or `manager/heartbeat.md`.
- The LLM decides what actions to run.
- Python executes those actions and loops until `HEARTBEAT_OK`.

Operational policy belongs in markdown (`heartbeat.md`, `bootstrap.md`, soul/skills), not hardcoded Python branches.

## Skill Authoring Contract

Each skill markdown should include these sections in order:

1. `# Skill: <Name>`
2. `## Type` (`Core` or `Learned`)
3. `## Purpose`
4. `## Actions / Usage`
5. `## Constraints`
6. `## Examples`
7. `## Failure / Escalation`

### Rules

- Core skills must list exact action names and parameters as implemented in dispatcher/runtime code.
- Learned skills must stay markdown-only. Do not add Python code as part of a learned skill.
- Keep one concern per file. If a learned skill grows too large, split by domain and link from an index file.

## Runtime Mapping Table

| Skill | Type | Dispatcher Actions | Runtime Module |
|---|---|---|---|
| `browser_automation.md` | Core | `navigate`, `click`, `type`, `scroll`, `execute_js`, `wait` | `macgent/actions/dispatcher.py`, `macgent/actions/safari_actions.py` |
| `browser-agent.md` | Core | `browser_task` | `macgent/actions/browser_use_action.py`, `macgent/actions/agent_browser.py` |
| `macos.md` | Core | `mail_*`, `calendar_*`, `imessage_*`, `open_app` | `macgent/actions/mail_actions.py`, `calendar_actions.py`, `imessage_actions.py` |
| `email_operations.md` | Core | `mail_read`, `mail_read_full`, `mail_send`, `mail_reply` | `macgent/actions/mail_actions.py` |
| `files.md` | Core | `read_file`, `write_file`, `edit_file`, `delete_file` | `macgent/actions/dispatcher.py` |
| `brave_search.md` | Core | `brave_search` | `macgent/actions/brave_search.py`, `macgent/actions/dispatcher.py` |
| `workspace/skills/notion.md` | Learned | `notion_*` usage reference only | Runtime implemented in `macgent/actions/notion_actions.py` |
| `evaluate_image.md` | Core | `evaluate_image` | `macgent/actions/dispatcher.py` + vision fallback chain |

## Browser Strategy

`BROWSER_MODE=agent_browser` is the supported runtime for web execution in the current architecture.

`BROWSER_HEADED=false` keeps browser windows hidden (recommended for normal runs).
Set `BROWSER_HEADED=true` only for debugging visual interactions.

Captcha policy:

- Detect challenge signals (`captcha`, `verify human`, `not a robot`, and anti-bot pages)
- Allow one auto-attempt (`CAPTCHA_AUTO_ATTEMPTS=1` by default)
- If still unsolved, return blocked with artifact path under `workspace/browser_runs/<timestamp>/`

## Model Routing

Defaults:

- Browser reasoning: `arcee-ai/trinity-large-preview:free`
- Browser vision: `nvidia/nemotron-nano-12b-v2-vl:free`

Optional last-resort model can be configured via environment (for example KILO model names), but free OpenRouter defaults stay primary.

Unified model routing knobs:
- `TEXT_MODEL_PRIMARY` and `TEXT_MODEL_FALLBACKS`
- `VISION_MODEL_PRIMARY` and `VISION_MODEL_FALLBACKS`

Built-in aliases:
- Text: `openrouter_primary`, `openrouter_trinity`, `openrouter_nemotron_text`, `kilo_glm5`, `kilo_glm47`
- Vision: `openrouter_vision_primary`, `openrouter_nemotron_vl`

Unknown alias values are treated as direct model IDs on the primary provider base URL.

## Adding a New Core Skill

1. Create/update `macgent/skills/<skill>.md` with the authoring contract.
2. Implement runtime actions in dispatcher/actions modules.
3. Add prompt references if needed (`macgent/prompts/`).
4. Add tests for action dispatch and failure behavior.
5. Update mapping table in this file.

## Adding a New Learned Skill

1. Create `workspace/skills/<skill>.md`.
2. Document usage patterns, schemas, edge cases.
3. Keep it markdown-only (no runtime module required).
4. Add links from `skills/README.md` or manager docs if relevant.

## Observability and Artifacts

Browser delegation writes artifacts to:

- `workspace/browser_runs/<timestamp>/result.json`
- `workspace/browser_runs/<timestamp>/page.png` (best effort)
- `workspace/browser_runs/<timestamp>/error.txt` (on failure)

Logs include backend selection, fallback reason, detection signals, and completion status.


## Centralized Error Management

LLM retries/fallback are centralized in `FallbackLLMClient`:
- Retries on configured HTTP statuses (default: 429, 503, 504)
- Exponential backoff per offer
- Automatic fallback to next offer when retries are exhausted

Tune this in `macgent_config.json -> error_policy` with:
- `retry_statuses`
- `max_retries_per_offer`
- `backoff_seconds`
- `backoff_multiplier`
