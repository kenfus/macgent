# Memory System

The macgent memory system is designed to help agents learn, remember, and improve over time. It has **three layers**: Souls (permanent character), Short-term memory (recent interactions), and Long-term memory (semantic knowledge).

## Overview

```
┌─────────────────────────────────────────────────────┐
│                  Agent Context                      │
├─────────────────────────────────────────────────────┤
│  1. Soul          → Permanent personality & rules   │
│  2. Short-term    → Recent task interactions        │
│  3. Long-term     → Semantic memories from past     │
└─────────────────────────────────────────────────────┘
```

When an agent runs, it builds its context from all three layers, giving it:
- **Character consistency** (soul)
- **Task continuity** (short-term)
- **Learning & patterns** (long-term)

## Layer 1: Souls (Permanent Character)

Each agent role has a **soul file** that defines its personality, responsibilities, and approach.

### Files
Soul files are stored in `~/.macgent/souls/`:
- `manager.md` - Manages the task board and monitors notifications
- `worker.md` - Executes tasks using browser automation
- `stakeholder.md` - Reviews quality and approves tasks

### How It Works

When an agent starts:
1. The agent's soul file is loaded
2. The soul becomes the system prompt for the LLM
3. Everything the agent does is filtered through this character

Example: A worker's soul includes:
- "Always dismiss cookie popups"
- "Use element indices for clicking"
- "Send unclear tasks to Stakeholder for clarification"

### Customizing Souls

Edit a soul to change how that agent behaves:

```bash
uv run macgent soul edit manager
uv run macgent soul edit worker
uv run macgent soul edit stakeholder
```

Or view without editing:

```bash
uv run macgent soul show manager
```

### Soul File Structure

```markdown
# [Role] Soul

Description of the agent's identity and purpose.

## Responsibilities
- What the agent is responsible for
- What the agent should focus on

## Approach
- How to solve problems
- Best practices
- Guidelines

## Skills
- What the agent can do
- Available tools
```

## Layer 2: Short-term Memory (Task Interactions)

Short-term memory records **recent interactions** within a specific task. It's stored in the SQLite database.

### What Gets Recorded

For each task, macgent records:
- Worker's initial plan (before execution)
- Stakeholder's feedback on the plan
- Worker's execution steps and results
- Stakeholder's review and approval/rejection
- Any communication between agents

### How Agents Use It

When an agent processes a task:
1. It retrieves recent interactions for that task (last 10 turns)
2. These become part of the agent's context
3. The agent understands the history and conversation

Example flow:
```
1. Worker sends plan: "I will navigate to the website and search..."
2. Stakeholder reviews: "Good, but please also check for price ranges"
3. Worker sees the feedback and adjusts execution accordingly
4. Stakeholder reviews result: "Perfect! Approved."
```

### Accessing Short-term Memory

The system automatically loads short-term memory. You can view recent interactions:

```bash
uv run macgent log -n 20
```

This shows recent turns, but doesn't include the full conversation context (that's internal).

## Layer 3: Long-term Memory (Semantic Learning)

Long-term memory lets agents remember **lessons from past tasks** and apply them to new tasks.

### Technology

- **Storage**: SQLite database (`~/.macgent/memory.db`)
- **Embedding**: `fastembed` (BAAI/bge-small-en-v1.5 model)
- **Vector Index**: FAISS (Facebook's similarity search)

### How It Works

When a task completes:
1. Agent extracts a "lesson" or "pattern" from the task
2. The lesson is embedded using the fastembed model
3. The embedding is stored in FAISS for fast semantic search
4. The text is stored in SQLite for retrieval

When starting a new task:
1. The task description is used to search long-term memory
2. FAISS finds semantically similar past experiences (top 5)
3. These are added to the agent's context
4. The agent can apply previous lessons

Example:
```
Past lesson: "When searching for hotels on Booking.com,
dismiss the login popup first, then click the search field"

New task: "Search for flights on Expedia"

Recall result: Similar task about dismissing popups on travel sites
→ Agent applies the lesson automatically
```

### Recording Memories

Agents record memories through the MemoryManager:

```python
from macgent.memory import MemoryManager

memory = MemoryManager(config)
memory.remember(
    db=db,
    role="worker",
    content="When clicking search fields, use element index instead of text matching",
    category="pattern",
    task_id=123,
    confidence=0.95
)
```

Categories:
- `pattern` - Reusable patterns (e.g., "dismiss popups first")
- `lesson` - Learned lessons (e.g., "this website doesn't work with this approach")
- `fact` - Useful facts (e.g., "company email uses two-factor auth")
- `error` - Errors to avoid (e.g., "don't use rm -rf in scripts")

### Semantic Search

Memories are retrieved by semantic similarity, not keyword matching:

```python
# This finds memories about "clicking buttons on forms"
# even if previous memories said "pressing submit on input fields"
memories = memory.recall(
    db=db,
    role="worker",
    query="How do I interact with form buttons?",
    top_k=5
)
```

### Checking Memory

View stored memories in the database:

```bash
sqlite3 ~/.macgent/memory.db "SELECT * FROM memories ORDER BY created_at DESC LIMIT 10;"
```

## The Complete Context

When an agent processes a task, its full context looks like:

```
[Agent Soul]
You are the Worker agent. You execute tasks using browser automation.
...

[Short-term Memory - Task History]
Manager: Task #42 - Search for hotels in Basel
Worker: Plan - I will navigate to Booking.com and search for hotels
Stakeholder: Approved plan, but check prices and ratings
Worker: Executing plan...

[Long-term Memory - Lessons]
- When searching travel sites, dismiss login popup first
- Use element [index] for clicking, not text matching
- For Booking.com specifically, wait 2s after search before scrolling
```

This combined context makes the agent effective because it:
- Stays in character (soul)
- Understands the current task (short-term)
- Learns from past mistakes (long-term)

## Memory Persistence

| Layer | Location | Persistence |
|-------|----------|------------|
| Soul | `~/.macgent/souls/*.md` | Manual edits, version control |
| Short-term | `~/.macgent/memory.db` (SQLite table: `turns`) | SQLite database |
| Long-term | `~/.macgent/memory.db` (SQLite) + FAISS index | FAISS file + DB |

All data is local. No cloud sync (unless you configure it).

## Clearing Memory

To start fresh without affecting souls:

```bash
# Clear only long-term memory (FAISS index)
rm ~/.macgent/faiss.index

# Clear only short-term memory (task interactions)
# This keeps the task record but deletes the conversation
sqlite3 ~/.macgent/memory.db "DELETE FROM turns WHERE 1=1;"

# Clear everything except souls (DANGEROUS!)
rm ~/.macgent/memory.db ~/.macgent/faiss.index
```

## Best Practices

1. **Review and improve souls regularly** - If agents aren't following a pattern you want, update their soul
2. **Monitor memories** - Check `uv run macgent log` to see what agents are learning
3. **Test before customizing** - Run examples before editing souls to establish baseline
4. **Keep souls concise** - Shorter souls are more effective (LLM attention)
5. **Use task isolation** - Keep tasks focused so lessons are specific and reusable

## Future Enhancements

Potential improvements to the memory system:
- [ ] **Forgetting mechanism** - Automatically prune old memories to stay focused
- [ ] **Confidence decay** - Reduce confidence of old memories over time
- [ ] **Memory editing** - Manually update or delete specific memories
- [ ] **Cross-agent learning** - Share relevant memories between roles
- [ ] **Explicit memory queries** - Agents can ask "what did I learn about this?"

## Troubleshooting

### "fastembed not installed"
Long-term memory requires fastembed. Install with:
```bash
uv pip install fastembed faiss-cpu
```

### "FAISS index corrupted"
Delete and regenerate:
```bash
rm ~/.macgent/faiss.index
# On next run, index will be recreated
```

### Memory getting too large
Current behavior: FAISS index grows indefinitely. Monitor size:
```bash
ls -lh ~/.macgent/faiss.index
```

If too large, clear and start fresh (memories are still in SQLite).

## See Also

- [SOUL.md](./SOUL.md) - Guide to understanding and customizing agent souls
- [Roles and Responsibilities](../macgent/roles/) - Implementation of each agent role
- [Examples](../examples/) - See memory in action through examples
