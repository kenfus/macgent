# Workspace Files

All paths are relative to the workspace root. You cannot escape outside it.

## read_file

Read a file. Returns numbered lines. Use `offset` and `limit` to read a slice (1-indexed).

```json
{"type": "read_file", "params": {"path": "<path>"}}
{"type": "read_file", "params": {"path": "<path>", "offset": <line_start>, "limit": <num_lines>}}
```

## write_file

Create or fully overwrite a file. Use for new files or when replacing everything.

```json
{"type": "write_file", "params": {"path": "<path>", "content": "<content>"}}
```

## append_file

Append content to the end of a file. Creates the file if it does not exist.

```json
{"type": "append_file", "params": {"path": "<path>", "content": "<content_to_append>"}}
```

## append_to_daily_memory

Append text to today's daily memory file at:
`<workspace>/memory/<YYYY-MM-DD>_MEMORY.md`

Input is cleaned as `text.strip()` and then written with exactly one trailing newline.

```json
{"type": "append_to_daily_memory", "params": {"text": "<memory_text>"}}
```

## edit_file

Replace an exact string in a file. The `old_string` must match exactly once — make it specific enough. Read the file first if unsure of the exact text.

```json
{"type": "edit_file", "params": {
  "path": "<path>",
  "old_string": "<old_string>",
  "new_string": "<new_string>"
}}
```

Returns an error if `old_string` is not found or matches more than once.

## delete_file

Delete a file in the workspace. Cannot delete directories or escape outside the workspace root.

```json
{"type": "delete_file", "params": {"path": "<path>"}}
```

Returns an error if the file does not exist.
