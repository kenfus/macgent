# Souls: Agent Character and Behavior

Each agent in macgent has a **soul** — a character definition that guides how it thinks, decides, and acts. The soul is the bridge between raw capability (skills) and intelligent behavior (wisdom).

## What is a Soul?

A soul is a **markdown file** that defines:
- **Identity**: Who the agent is ("You are the Worker agent")
- **Responsibilities**: What the agent should do
- **Approach**: How to solve problems
- **Constraints**: Rules and guidelines to follow
- **Skills**: What tools are available and how to use them

The soul becomes the **system prompt** for the LLM, making it the agent's constitutional guide.

## The Three Souls

### Manager Soul

**Role**: Monitor notifications and manage the task board.

**Responsibilities**:
- Check email for actionable items
- Classify by priority (P1-P4)
- Create tasks for important items
- Monitor stale tasks
- Escalate to CEO when overwhelmed

**Key Behaviors**:
- Reads email every heartbeat
- Runs heuristics to classify importance
- Doesn't create tasks for newsletters or calendar invites
- Pings the Worker if tasks are stuck

### Worker Soul

**Role**: Execute tasks using browser automation and macOS tools.

**Responsibilities**:
- Receive tasks from the board
- Send plans to Stakeholder for clarification
- Execute after approval
- Handle errors and retry (up to 3 rounds)

**Key Behaviors**:
- Always dismisses popups first (before other actions), such as cookies (accept them), or ADs, or logins (such as google or instagram).
- Uses element [index] for clicking (not text)
- Doesn't log in unless explicitly asked
- Sends unclear tasks to Stakeholder instead of guessing

**Key Constraint**:
```
The Stakeholder must approve before execution.
Don't execute tasks you don't understand.
```

### Stakeholder Soul

**Role**: Review quality and ensure work meets standards.

**Responsibilities**:
- Review worker's plan (clarification phase)
- Review worker's result (quality phase)
- Approve or provide feedback
- Escalate when tasks are ambiguous or impossible

**Key Behaviors**:
- Asks clarifying questions about ambiguous plans
- Checks if results actually address the task
- Rejects with specific, actionable feedback
- Escalates after 3 failed attempts

## Editing Souls

### View Your Current Souls

```bash
uv run macgent soul show manager
uv run macgent soul show worker
uv run macgent soul show stakeholder
```

### Edit a Soul

```bash
uv run macgent soul edit manager
uv run macgent soul edit worker
uv run macgent soul edit stakeholder
```

This opens your `$EDITOR` (nano, vim, etc.) with the soul file.

### Soul File Locations

After first run, souls are created at:
```
~/.macgent/souls/manager.md
~/.macgent/souls/worker.md
~/.macgent/souls/stakeholder.md
```

You can also edit them directly:

```bash
nano ~/.macgent/souls/worker.md
```

## Example: Customizing the Worker Soul

Default worker doesn't log in to sites. To change this:

```bash
uv run macgent soul edit worker
```

Find this section:
```markdown
### Login / Sign-In Popups
- DEFAULT: DISMISS login prompts (click X, "Close", "No thanks", "Continue as guest")
- Do NOT log in with Google, Apple, Facebook, or any SSO unless the task explicitly says to
```

Change to:
```markdown
### Login / Sign-In Popups
- If task requires login, use credentials from password manager
- For Google/Apple/Facebook SSO, use those if available
- Try "Continue as guest" if available first
```

Save and run a task:
```bash
uv run macgent task 'Go to Gmail and check my recent emails'
```

The worker will now attempt login.

## Soul Structure Best Practices

### DO ✓
- Keep souls **short and focused** (LLM attention matters)
- Use **clear sections** with headers
- Write **specific behavior rules** ("Always dismiss popups first")
- Include **examples** when helpful
- Use **bullet points** for easy scanning

### DON'T ✗
- Write long essays or over-explain
- Include irrelevant philosophy
- Use vague language ("be smart", "do your best")
- Duplicate instructions (keep it DRY)
- Include code examples unless necessary

### Example Good Soul Structure

```markdown
# Worker Soul

You are the Worker agent executing tasks via browser automation.

## Workflow
1. Receive task
2. Send plan to Stakeholder
3. Wait for approval
4. Execute
5. Report result

## Key Rules
- Always dismiss popups FIRST
- Use element [index] for clicking
- Don't log in unless explicitly asked
- For unclear tasks, ask Stakeholder

## Browser Tips
- [Short, actionable tips]
```

## Common Customizations

### Make Workers More Aggressive

If workers are too cautious:

```markdown
## Task Interpretation
- If task is ambiguous, make reasonable assumptions
- Try the most likely interpretation
- Report what you attempted and what you found
```

### Make Workers More Conservative

If workers are making mistakes:

```markdown
## Task Interpretation
- ALL tasks must be crystal clear before execution
- Ask Stakeholder about ANY ambiguity
- Never guess at intent
```

### Change Quality Standards

In Stakeholder soul:

```markdown
## Quality Criteria
- [Your criteria here]
```

### Add Specific Domain Knowledge

For financial tasks, add to Worker soul:

```markdown
## Financial Task Guidelines
- Always verify currency and exchange rates
- Double-check calculations
- Flag any transactions over $1000
```

## Testing Soul Changes

After editing a soul:

1. Run the related example:
   ```bash
   bash examples/web_search_test.sh
   ```

2. Check the output for the new behavior

3. If unexpected, edit the soul again and retry

4. Use `uv run macgent log -n 10` to see what the agent did

## Soul Versioning

Souls are human-editable text files. You can:

- **Version control them**: `git add ~/.macgent/souls/`
- **Compare versions**: See what changed between runs
- **Roll back**: `git checkout` old soul versions
- **Merge changes**: If you have multiple branches

## Limits and Constraints

**What souls can do:**
- Define behavior and personality
- Provide guidelines and rules
- Explain how to use skills
- Set priorities and values

**What souls cannot do:**
- Add new technical capabilities (that requires code)
- Override the fundamental workflow (Manager→Worker→Stakeholder)
- Change how the LLM is called (that requires code changes)
- Grant skills that don't exist (JavaScript execution requires code, not soul)

## Advanced: Role-Specific Customization

### For a Specific Task

If you want a Worker to behave differently for one task:

1. Edit Worker soul temporarily
2. Run the task
3. Restore the original soul

(Future: task-specific soul overrides)

### By Domain

Create separate soul versions for different domains:

```
~/.macgent/souls/worker.md              (default)
~/.macgent/souls/worker-financial.md    (for financial tasks)
~/.macgent/souls/worker-travel.md       (for travel tasks)
```

Then implement logic to choose the right soul based on task type.

## Troubleshooting Soul Issues

### Agent behaves opposite of soul

**Problem**: Soul says "dismiss popups" but agent doesn't.

**Cause**: LLM didn't understand or prioritized something else.

**Solution**:
- Make the rule more explicit with an example
- Add it earlier in the soul
- Use stronger language ("ALWAYS", "FIRST")

### Agent ignores custom soul rules

**Problem**: Custom soul not applied.

**Cause**: Rules might be too vague or contradictory.

**Solution**:
- Make rules more specific
- Remove contradictions
- Add examples
- Check that soul file was saved correctly

### Agent behavior is inconsistent

**Problem**: Sometimes follows rule, sometimes doesn't.

**Cause**: LLM variability + ambiguous rules.

**Solution**:
- Make rules crystal clear
- Use examples with exact steps
- Test multiple times (LLM has inherent variance)

## See Also

- [MEMORY.md](./MEMORY.md) - How souls interact with memory layers
- [Skills Reference](../skills/) - Available capabilities
- [System Prompt](../macgent/prompts/) - Technical prompt implementation
- [Examples](../examples/) - See souls in action
