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

### Option 1: Run Bot in Polling Mode

```bash
# Continuous polling (Ctrl+C to stop)
uv run macgent telegram

# Single batch of messages
uv run macgent telegram --once
```

### Option 2: Run with Daemon

The telegram polling can run alongside the manager daemon:

```bash
# In one terminal
uv run macgent daemon

# In another terminal
uv run macgent telegram
```

Both processes share the same database and will coordinate:
- **Manager** checks for new tasks and manages the board
- **Worker** executes tasks
- **Stakeholder** reviews results
- **Telegram Bot** receives messages and sends notifications

## How It Works

### Incoming Messages
When a message is sent to the bot:
1. Bot receives and parses the message
2. Creates a task in the database with source `telegram_<user_id>`
3. Sends acknowledgment back to the user
4. Manager picks it up and routes to Worker/Stakeholder

### Task Updates
When a task status changes:
1. Bot sends status update to the original sender
2. Messages include:
   - Current status (⏳ pending, 🔄 in progress, ✅ completed, ❌ failed, ⚠️ escalated)
   - Task result (if available)
   - Stakeholder feedback (if any)

## Message Flow

```
CEO/Stakeholder
      ↓
[Message] → Telegram Bot receives
      ↓
[Task created] → Database (source: telegram_<user_id>)
      ↓
Manager reviews → Worker executes → Stakeholder approves
      ↓
[Status update] → Telegram notification sent back to CEO
```

## Features

- ✅ **Message Polling**: Asynchronous long polling to receive messages
- ✅ **Task Creation**: Automatic task creation from Telegram messages
- ✅ **Status Updates**: Real-time notifications when tasks complete/escalate
- ✅ **User Tracking**: Maintains chat_id for responses
- ✅ **Async Support**: Non-blocking Telegram API calls
- ✅ **Integration**: Seamlessly integrated with Worker/Stakeholder review loops

## Example Workflow

```
You (via Telegram):
"Check HackerNews top 3 stories and summarize"
        ↓
Bot: "✓ Task #5 received: Check HackerNews top 3 stories..."
        ↓
Worker executes task (navigates, reads, summarizes)
        ↓
Stakeholder reviews result
        ↓
Bot: "✅ Task #5
     Status: completed
     Result: 1) AI Policy... 2) GPU Makers... 3) Security..."
```

## Troubleshooting

### Bot not receiving messages
- Check that `TELEGRAM_BOT_TOKEN` is correct in `.env`
- Ensure the polling is running: `uv run macgent telegram`
- Look for error logs with timestamps

### Messages received but tasks not created
- Check database path: `macgent.db` in `~/.macgent/`
- Review logs: `uv run macgent log`
- Check task status: `uv run macgent status`

### Notifications not sent back
- Verify `telegram_bot.py` can import (check for syntax errors)
- Ensure chat_id is stored in the task's `review_note` field
- Check error logs for Telegram API failures

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
