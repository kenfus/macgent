# Email Operations Skill

Read emails from Mail app, send emails, and interact with email accounts.

## Actions

### read_email
Read recent emails from the inbox or specific folder.

```
Action: read_email
Params: {"folder": "INBOX", "limit": 5}
```

Returns:
- Email sender
- Subject
- Date received
- Email body/preview
- Attachment info if present

Folders:
- `INBOX` - Inbox
- `SENT` - Sent messages
- `DRAFTS` - Draft messages
- `TRASH` - Deleted messages
- Other folder names from your Mail app

### search_email
Search for emails by subject, sender, or content.

```
Action: search_email
Params: {"query": "from:boss@company.com", "limit": 10}
```

### send_email
Compose and send an email.

```
Action: send_email
Params: {
    "to": "recipient@example.com",
    "subject": "Test Email",
    "body": "Hello! This is a test message."
}
```

Parameters:
- `to` - Email address (required)
- `subject` - Email subject (required)
- `body` - Email body text (required)
- `cc` - CC recipients (optional, comma-separated)
- `bcc` - BCC recipients (optional, comma-separated)

### reply_email
Reply to an existing email.

```
Action: reply_email
Params: {
    "email_id": "12345",
    "body": "Thanks for your message!"
}
```

## Common Patterns

### Check Recent Emails
1. `read_email` from INBOX with limit 5
2. Extract sender, subject, date, content
3. Look for actionable items
4. Decide if response is needed

### Send Notification Email
1. `send_email` to recipient
2. Include task title in subject
3. Include summary in body
4. Confirm success

### Find Emails from a Person
1. `search_email` with "from:person@domain.com"
2. Extract recent messages
3. Look for patterns or requests
4. Plan response if needed

## Tips & Gotchas

- **Mail app must be running** - Email actions require the Mail app to be open
- **Folder names matter** - Use exact folder names from your Mail setup
- **HTML emails** - Email body text is extracted from HTML; formatting is lost but content is preserved
- **Large bodies** - Very long emails may be truncated in results
- **No attachment upload** - Can read attachments but cannot attach files in replies
- **Authentication** - Email must be configured in Mail app with valid credentials

## Related Skills

- [Calendar Operations](./calendar_operations.md) - Handle calendar invites in emails
- [Messages](./messages.md) - Send messages via iMessage instead of email
