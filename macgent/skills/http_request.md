# HTTP Request & Script Execution

## http_request — call any HTTP API

Make GET/POST/PUT/PATCH/DELETE requests to any URL. Returns the raw response body.

```json
{"type": "http_request", "params": {
  "method": "GET",
  "url": "https://api.example.com/endpoint",
  "headers": {"Authorization": "Bearer TOKEN", "Notion-Version": "2022-06-28"},
  "body": {"key": "value"},
  "timeout": 15
}}
```

- `method`: GET, POST, PUT, PATCH, DELETE (default: GET)
- `headers`: object of header key/value pairs
- `body`: object (auto-serialised as JSON) or string — omit for GET
- `timeout`: seconds before giving up (default 15)

Returns `HTTP 200\n<response body>` on success, or `HTTP 4xx ...\n<error body>` on failure.

### Notion API example

```json
{"type": "http_request", "params": {
  "method": "POST",
  "url": "https://api.notion.com/v1/databases/DATABASE_ID/query",
  "headers": {
    "Authorization": "Bearer SECRET",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
  },
  "body": {}
}}
```

Use env vars from your environment (NOTION_TOKEN, etc.) by referencing them in the header value string directly — you know the values from your core memory or .env file.

---

## run_script — write Python code and execute it

1. Write the script with `write_file` (path inside workspace, e.g. `scripts/notion.py`)
2. Execute it with `run_script` — stdout is returned as the result

```json
{"type": "run_script", "params": {
  "path": "scripts/notion.py",
  "args": ["--limit", "10"],
  "env": {"NOTION_TOKEN": "secret_..."},
  "timeout": 30
}}
```

- `path`: script path relative to workspace
- `args`: list of CLI arguments (optional)
- `env`: extra environment variables to inject (optional)
- `timeout`: seconds before killing the process (default 30)

Returns stdout, and [stderr] / [exit N] sections if there were errors.

---

## execute_script — run Python code inline (no file needed)

Write code directly in the action — no `write_file` step required.

```json
{"type": "execute_script", "params": {
  "code": "import os\nprint(os.environ.get('NOTION_TOKEN', 'not set'))",
  "env": {"EXTRA_VAR": "value"},
  "timeout": 30
}}
```

- `code`: Python source code as a string (multi-line fine)
- `env`: extra environment variables to inject (optional)
- `timeout`: seconds before killing the process (default 30)

Returns stdout, and [stderr] / [exit N] sections if there were errors.

---

### When to use which

| Situation | Use |
|-----------|-----|
| Single API call (Notion, GitHub, etc.) | `http_request` — simplest, no code needed |
| Quick computation or one-off snippet | `execute_script` — inline, no file needed |
| Complex logic you want to save and reuse | `run_script` — write file first, then run |
