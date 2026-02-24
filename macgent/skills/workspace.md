# Workspace Files

All paths are relative to the workspace root. You cannot escape outside it.

## read_file

Read a file. Returns numbered lines. Use `offset` and `limit` to read a slice (1-indexed).

```json
{"type": "read_file", "params": {"path": "skills/notion.md"}}
{"type": "read_file", "params": {"path": "manager/IDENTITY.md", "offset": 10, "limit": 20}}
```

## write_file

Create or fully overwrite a file. Use for new files or when replacing everything.

```json
{"type": "write_file", "params": {"path": "skills/notion.md", "content": "# Notion Skill\n..."}}
```

## edit_file

Replace an exact string in a file. The `old_string` must match exactly once — make it specific enough. Read the file first if unsure of the exact text.

```json
{"type": "edit_file", "params": {
  "path": "skills/notion.md",
  "old_string": "Status: In Progress",
  "new_string": "Status: Done"
}}
```

Returns an error if `old_string` is not found or matches more than once.
