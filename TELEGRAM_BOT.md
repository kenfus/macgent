# Telegram Bot Integration

macgent now supports Telegram Bot as a primary communication channel for CEO/stakeholder messages alongside mail.

## Setup

### 1. Create a Telegram Bot

1. Talk to [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts
3. You'll receive a bot token: `YOUR_BOT_TOKEN`

**Note:** A bot has already been created for this project: **@MacGentBot** (t.me/MacGentBot) with token:
```
7791953129:AAHVjI8maTBUetcTQMtwU7zqi3QhIyE_QjU
```

### 2. Configure .env

Add the following to your `.env` file:

```env
TELEGRAM_BOT_TOKEN=7791953129:AAHVjI8maTBUetcTQMtwU7zqi3QhIyE_QjU
TELEGRAM_CHAT_ID=your_chat_id
```

Get your chat ID by:
1. Starting a chat with the bot: https://t.me/MacGentBot
2. Sending any message
3. Running the bot in polling mode once - it will accept the message and you can derive the chat ID

Or use the Telegram Bot API directly to get updates.

## Usage

### Run the Unified Daemon

The Telegram bot is now **integrated into the daemon** — run one command:

```bash
# Start the unified manager daemon (includes Telegram polling)
uv run macgent daemon
```

Expected output:
```
macgent daemon started (interval=1800s, Ctrl+C to stop)
✓ Telegram bot enabled — listening on @MacGentBot
============================================================
Heartbeat cycle #1
  Manager: Checking email...
  Stakeholder: No tasks in review
  Worker: No pending tasks
Sleeping 1800s until next heartbeat (or until external wake signal)...
```

Now send a message to @MacGentBot on Telegram — the daemon will wake immediately and process it.

### Single Cycle Test

```bash
# Run one heartbeat cycle, then exit (useful for quick testing)
uv run macgent daemon --once
```

## How It Works

### Incoming Messages (Passive Notifications)
When a message is sent to the bot:
1. Bot receives and parses the message
2. Creates a task in the database with source `telegram_<user_id>` and priority 2
3. **Sends wake signal to Manager** (triggers immediate heartbeat)
4. Sends acknowledgment back to the user
5. Manager wakes up immediately (even if sleeping on the daemon interval)
6. Manager → Worker → Stakeholder processes the task

This is a **passive notification** system - the Manager gets pinged when messages arrive.

### Task Updates
When a task status changes:
1. Worker notifies via Telegram back to the original sender
2. Messages include:
   - Current status (⏳ pending, 🔄 in progress, ✅ completed, ❌ failed, ⚠️ escalated)
   - Task result (if available)
   - Stakeholder feedback (if any)

### Active Monitoring
The Manager also **actively checks** various sources:
- 📧 **Email Monitor** - Checks for new emails and classifies them into tasks
- 📋 Notion boards (not yet implemented)
- 📌 Slack channels (not yet implemented)

These are checked periodically during each heartbeat cycle.

## Message Flow

```
Active Sources (checked every heartbeat):
  Email → Manager classifies → Task created

Passive Sources (ping Manager immediately):
  Telegram/Slack message → Task created → Manager wakes up NOW
                                 ↓
                         (vs waiting for next heartbeat)
                                 ↓
  Manager → Worker executes → Stakeholder approves
                                 ↓
                    Telegram notification sent back
```

### Example Timeline

```
Time 0:00 - Manager heartbeat (active: check email, monitor board)
Time 0:15 - CEO sends Telegram message
          → Task created instantly
          → Manager wakes from sleep (⚡)
          → Manager/Worker/Stakeholder process immediately
          → Result sent back within seconds
Time 0:30 - Next scheduled heartbeat
```

## Features

- ✅ **Message Polling**: Asynchronous long polling to receive messages
- ✅ **Task Creation**: Automatic task creation from Telegram messages
- ✅ **Status Updates**: Real-time notifications when tasks complete/escalate
- ✅ **User Tracking**: Maintains chat_id for responses
- ✅ **Async Support**: Non-blocking Telegram API calls
- ✅ **Integration**: Seamlessly integrated with Worker/Stakeholder review loops

## Example Workflow

The Telegram bot runs inside the daemon — one unified process handles everything:

```
Timeline:
=========

00:00 - Manager daemon starts
        ✓ Telegram bot enabled — listening on @MacGentBot
        Heartbeat cycle #1: check email, manage board

00:15 - YOU (via Telegram):
        "Check HackerNews top 3 stories and summarize"

        Inside daemon:
        ├─ Async task: Telegram bot receives message
        ├─ Creates task #1 in database
        ├─ Wakes the manager (sets _wake_request flag)
        └─ Sends you: "✓ Task #1 received..."

        Manager (in sync thread):
        ├─ Detects _wake_request
        ├─ ⚡ Waking early due to external notification!
        ├─ Heartbeat cycle #2: Process task #1
        ├─ Worker: Executing task (navigates, reads, summarizes)
        ├─ Stakeholder: Reviews and approves
        └─ Sends you: "✅ Task #1 completed - Results: ..."

00:16 - YOU (via Telegram):
        Receive: ✅ Task #1
                 Status: completed
                 Result: 1) AI Policy... 2) GPU Makers... 3) Security...
```

## Troubleshooting

### Bot not receiving messages
- Verify `TELEGRAM_BOT_TOKEN` is set correctly in `.env`
- Ensure daemon is running: `uv run macgent daemon`
- Look for "Telegram bot enabled" in the startup output
- Check you're messaging **@MacGentBot** (not a different bot)
- Look for error logs with timestamps

### "Telegram not configured" message
- Set `TELEGRAM_BOT_TOKEN` in `.env`
- Restart the daemon: `uv run macgent daemon`

### Messages received but tasks not created
- Check daemon logs for errors
- Review task status: `uv run macgent status`
- View logs: `uv run macgent log -n 50`
- Check database path: `~/.macgent/macgent.db`

### Daemon not waking when message arrives
- Verify chat_id is in task metadata (stored in `review_note`)
- Check that Manager's `should_wake_early()` is being called
- Look for "Waking early" in daemon output

### Notifications not sent back to Telegram
- Ensure Worker has the chat_id metadata from the task
- Check Telegram API key is correct
- Review error logs for Telegram API failures

## Limitations

- Long polling may have slight delays (30s timeout)
- Messages over Telegram's character limit will be truncated
- Currently single-user (one chat ID per bot)

## Future Enhancements

- [ ] Support for multiple chat IDs
- [ ] Webhook mode (instead of polling) for real-time updates
- [ ] Callback buttons for quick actions
- [ ] File/image attachment handling
- [ ] Inline keyboard for task review approval
