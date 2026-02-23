"""Notion REST API actions for managing the planning board.

Notion is the SINGLE SOURCE OF TRUTH for all tasks. No SQLite task storage.
"""

import logging
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger("macgent.actions.notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Properties we need to ensure exist (won't touch existing ones like Status, Priority, Task Name).
REQUIRED_EXTRA_PROPERTIES = {
    "Description": {"rich_text": {}},
    "Source": {"rich_text": {}},
    "MacgentID": {"number": {"format": "number"}},
    "Notes": {"rich_text": {}},
}

# Detected at runtime by ensure_schema().
# "status" = Notion built-in, "select" = custom select.
_status_prop_type = "status"

# Map our internal status names → actual Notion option names.
# Adapt if the Notion board uses different labels.
STATUS_MAP = {
    "Inbox": "Backlog",
    "Ready": "Ready to be worked on",
    "In Progress": "In Progress",
    "Done": "Complete",
    "Blocked": "Blocked",
}
# Reverse map: Notion option name → our internal name.
STATUS_REVERSE = {v: k for k, v in STATUS_MAP.items()}

# Map our internal priority (int) → Notion option names.
PRIORITY_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
# Reverse: Notion name → our internal name (kept as-is for display).
PRIORITY_REVERSE = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}

# Title property name in Notion (may be "Name" or "Task Name" etc.)
_title_prop = "Task Name"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _parse_page(page: dict) -> dict:
    """Parse a Notion page into a flat task dict."""
    props = page.get("properties", {})

    # Title — try detected property name, fall back to "Name"
    title_parts = props.get(_title_prop, props.get("Name", {})).get("title", [])
    title = "".join(t.get("plain_text", "") for t in title_parts)

    # Status — handle both "status" (built-in) and "select" types
    status_prop = props.get("Status", {})
    status_type = status_prop.get("type", _status_prop_type)
    raw_status = (status_prop.get(status_type) or {}).get("name", "")
    page_status = STATUS_REVERSE.get(raw_status, raw_status)

    # Priority
    raw_priority = (props.get("Priority", {}).get("select") or {}).get("name", "")
    priority = PRIORITY_REVERSE.get(raw_priority, raw_priority)

    macgent_id = props.get("MacgentID", {}).get("number")
    desc_parts = props.get("Description", {}).get("rich_text", [])
    description = "".join(t.get("plain_text", "") for t in desc_parts)
    notes_parts = props.get("Notes", {}).get("rich_text", [])
    notes = "".join(t.get("plain_text", "") for t in notes_parts)
    source_parts = props.get("Source", {}).get("rich_text", [])
    source = "".join(t.get("plain_text", "") for t in source_parts)

    page_id = page["id"]
    return {
        "page_id": page_id,
        "id": page_id,                     # alias for code that expects task["id"]
        "title": title,
        "status": page_status,
        "priority": priority,
        "macgent_id": macgent_id,
        "description": description,
        "notes": notes,
        "source": source,
        "notion_page_id": page_id,          # alias for code that expects task["notion_page_id"]
        "last_edited_time": page.get("last_edited_time", ""),
    }


def ensure_schema(token: str, database_id: str) -> bool:
    """Ensure the Notion database has required extra properties. Detects existing schema."""
    global _status_prop_type, _title_prop
    if not token or not database_id:
        logger.warning("Notion token or database_id not configured, skipping schema check")
        return False

    try:
        # Get current database schema
        resp = httpx.get(
            f"{NOTION_API}/databases/{database_id}",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        existing = resp.json().get("properties", {})
        existing_names = set(existing.keys())

        # Detect Status property type (Notion built-in "status" vs custom "select")
        if "Status" in existing:
            detected = existing["Status"].get("type", "select")
            _status_prop_type = detected
            logger.info(f"Notion Status property type: {detected}")

        # Detect title property name (could be "Name", "Task Name", etc.)
        for name, prop in existing.items():
            if prop.get("type") == "title":
                _title_prop = name
                logger.info(f"Notion title property: '{name}'")
                break

        # Only add missing extra properties (Description, Source, Notes, MacgentID)
        missing = {k: v for k, v in REQUIRED_EXTRA_PROPERTIES.items()
                   if k not in existing_names}
        if not missing:
            logger.info("Notion database schema is up to date")
            return True

        logger.info(f"Adding missing Notion properties: {list(missing.keys())}")
        patch_resp = httpx.patch(
            f"{NOTION_API}/databases/{database_id}",
            headers=_headers(token),
            json={"properties": missing},
            timeout=10,
        )
        patch_resp.raise_for_status()
        logger.info("Notion database schema updated successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to ensure Notion schema: {e}")
        return False


def create_task(
    token: str,
    database_id: str,
    title: str,
    description: str = "",
    priority: int = 3,
    source: str = "",
    status: str = "Ready",
    note: str = "",
) -> str | None:
    """Create a new task page in the Notion database. Returns the page_id or None."""
    if not token or not database_id:
        logger.warning("Notion not configured, skipping create_task")
        return None

    priority_label = PRIORITY_MAP.get(priority, "Medium")
    notion_status = STATUS_MAP.get(status, status)

    properties: dict = {
        _title_prop: {"title": [{"text": {"content": title[:100]}}]},
        "Status": {_status_prop_type: {"name": notion_status}},
        "Priority": {"select": {"name": priority_label}},
    }
    if description:
        properties["Description"] = {
            "rich_text": [{"text": {"content": description[:2000]}}]
        }
    if source:
        properties["Source"] = {
            "rich_text": [{"text": {"content": source[:200]}}]
        }
    if note:
        properties["Notes"] = {
            "rich_text": [{"text": {"content": note[:2000]}}]
        }

    try:
        resp = httpx.post(
            f"{NOTION_API}/pages",
            headers=_headers(token),
            json={"parent": {"database_id": database_id}, "properties": properties},
            timeout=10,
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]
        logger.info(f"Created Notion task '{title}' → {page_id}")
        return page_id
    except Exception as e:
        logger.error(f"Failed to create Notion task: {e}")
        return None


def update_task(
    token: str,
    page_id: str,
    status: str | None = None,
    note: str | None = None,
) -> bool:
    """Update a Notion task's Status and/or Notes."""
    if not token or not page_id:
        return False

    properties: dict = {}
    if status:
        notion_status = STATUS_MAP.get(status, status)
        properties["Status"] = {_status_prop_type: {"name": notion_status}}
    if note:
        properties["Notes"] = {
            "rich_text": [{"text": {"content": note[:2000]}}]
        }

    if not properties:
        return True

    try:
        resp = httpx.patch(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": properties},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"Updated Notion page {page_id}: status={status}")
        return True
    except Exception as e:
        logger.error(f"Failed to update Notion task {page_id}: {e}")
        return False


def list_tasks(
    token: str,
    database_id: str,
    status: str | None = None,
) -> list[dict]:
    """Query the Notion database. Returns list of task dicts."""
    if not token or not database_id:
        return []

    body: dict = {"page_size": 50}
    if status:
        notion_status = STATUS_MAP.get(status, status)
        body["filter"] = {
            "property": "Status",
            _status_prop_type: {"equals": notion_status},
        }

    try:
        resp = httpx.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json=body,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Notion query failed ({resp.status_code}): {resp.text[:500]}")
            return []
        results = resp.json().get("results", [])

        tasks = []
        for page in results:
            tasks.append(_parse_page(page))
        return tasks
    except Exception as e:
        logger.error(f"Failed to list Notion tasks: {e}")
        return []


def get_task(token: str, page_id: str) -> dict | None:
    """Get a single Notion task page. Returns full task dict or None."""
    if not token or not page_id:
        return None

    try:
        resp = httpx.get(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        return _parse_page(resp.json())
    except Exception as e:
        logger.error(f"Failed to get Notion task {page_id}: {e}")
        return None


def next_ready_task(token: str, database_id: str) -> dict | None:
    """Get highest-priority Ready task from Notion. Returns task dict or None."""
    tasks = list_tasks(token, database_id, status="Ready")
    if not tasks:
        return None
    priority_order = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    tasks.sort(key=lambda t: priority_order.get(t["priority"], 99))
    return tasks[0]


def get_stale_tasks(token: str, database_id: str, minutes: int = 60) -> list[dict]:
    """Get In Progress tasks not edited in the last N minutes."""
    if not token or not database_id:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    notion_status = STATUS_MAP.get("In Progress", "In Progress")
    body = {
        "filter": {
            "and": [
                {"property": "Status", _status_prop_type: {"equals": notion_status}},
                {"timestamp": "last_edited_time", "last_edited_time": {"before": cutoff}},
            ]
        },
        "page_size": 50,
    }

    try:
        resp = httpx.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json=body,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Notion stale query failed ({resp.status_code}): {resp.text[:500]}")
            return []
        results = resp.json().get("results", [])
        return [_parse_page(page) for page in results]
    except Exception as e:
        logger.error(f"Failed to get stale Notion tasks: {e}")
        return []
