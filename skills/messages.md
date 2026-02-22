# Messages (iMessage) Skill

Send and read iMessages through Apple's Messages app.

## Actions

### send_message
Send an iMessage to a contact.

```
Action: send_message
Params: {
    "to": "+1 555 123 4567",
    "text": "Hello! Is this a good time to chat?"
}
```

Parameters:
- `to` - Phone number or contact name (required)
- `text` - Message text (required)
- `attachments` - File paths (optional, not yet supported)

### read_messages
Read recent messages from a conversation.

```
Action: read_messages
Params: {
    "contact": "+1 555 123 4567",
    "limit": 10
}
```

Returns:
- Message text
- Sender
- Timestamp
- Read status

Parameters:
- `contact` - Phone number or contact name
- `limit` - Number of recent messages to retrieve (default: 10)

### search_messages
Search messages for a contact or keyword.

```
Action: search_messages
Params: {
    "query": "meeting",
    "contact": "+1 555 123 4567"
}
```

## Common Patterns

### Send Quick Message
1. `send_message` with recipient and text
2. Wait for delivery confirmation
3. Task complete

### Check Recent Messages from Contact
1. `read_messages` from contact with limit 5
2. Extract recent conversation context
3. Decide if response is needed

### Follow Up on Previous Conversation
1. `read_messages` to get conversation history
2. Understand previous context
3. `send_message` with follow-up message

## Tips & Gotchas

- **Messages app must be running** - iMessage requires Messages app to be open
- **Phone numbers** - Use format with country code for best results
- **Contact names** - If contact is in Contacts app, can use full name
- **Delivery may be slow** - iMessage delivery is async; may take a moment
- **No read receipts** - Cannot check if message was read
- **Rich content limited** - Can send text; attachments not yet supported
- **Conversation history** - Full message history is available for search/read

## Related Skills

- [Email Operations](./email_operations.md) - Send email instead of iMessage
