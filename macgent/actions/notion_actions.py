"""Notion REST API actions for managing the planning board."""

import logging
import httpx

logger = logging.getLogger("macgent.actions.notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Required database properties and their types
REQUIRED_PROPERTIES = {
    "Status": {
        "select": {
            "options": [
                {"name": "Inbox", "color": "gray"},
                {"name": "Ready", "color": "blue"},
                {"name": "In Progress", "color": "yellow"},
                {"name": "Done", "color": "green"},
                {"name": "Failed", "color": "red"},
                {"name": "Escalated", "color": "orange"},
            ]
        }
    },
    "Priority": {
        "select": {
            "options": [
                {"name": "P1", "color": "red"},
                {"name": "P2", "color": "orange"},
                {"name": "P3", "color": "yellow"},
                {"name": "P4", "color": "gray"},
            ]
        }
    },
    "Description": {"rich_text": {}},
    "Source": {"rich_text": {}},
    "MacgentID": {"number": {"format": "number"}},
    "Notes": {"rich_text": {}},
}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def ensure_schema(token: str, database_id: str) -> bool:
    """Ensure the Notion database has all required properties. Creates missing ones."""
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

        missing = {k: v for k, v in REQUIRED_PROPERTIES.items() if k not in existing_names}
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
    task_id: int | None = None,
) -> str | None:
    """Create a new task page in the Notion database. Returns the page_id or None."""
    if not token or not database_id:
        logger.warning("Notion not configured, skipping create_task")
        return None

    priority_map = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
    priority_label = priority_map.get(priority, "P3")

    properties: dict = {
        "Name": {"title": [{"text": {"content": title[:100]}}]},
        "Status": {"select": {"name": status}},
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
    if task_id is not None:
        properties["MacgentID"] = {"number": task_id}

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
        properties["Status"] = {"select": {"name": status}}
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
        body["filter"] = {
            "property": "Status",
            "select": {"equals": status},
        }

    try:
        resp = httpx.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        tasks = []
        for page in results:
            props = page.get("properties", {})
            title_parts = props.get("Name", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            page_status = (props.get("Status", {}).get("select") or {}).get("name", "")
            priority = (props.get("Priority", {}).get("select") or {}).get("name", "")
            macgent_id = (props.get("MacgentID", {}).get("number"))
            desc_parts = props.get("Description", {}).get("rich_text", [])
            description = "".join(t.get("plain_text", "") for t in desc_parts)
            tasks.append({
                "page_id": page["id"],
                "title": title,
                "status": page_status,
                "priority": priority,
                "macgent_id": macgent_id,
                "description": description,
            })
        return tasks
    except Exception as e:
        logger.error(f"Failed to list Notion tasks: {e}")
        return []


def get_task(token: str, page_id: str) -> dict | None:
    """Get a single Notion task page."""
    if not token or not page_id:
        return None

    try:
        resp = httpx.get(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        page = resp.json()
        props = page.get("properties", {})
        title_parts = props.get("Name", {}).get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)
        return {
            "page_id": page["id"],
            "title": title,
            "status": (props.get("Status", {}).get("select") or {}).get("name", ""),
            "priority": (props.get("Priority", {}).get("select") or {}).get("name", ""),
            "macgent_id": props.get("MacgentID", {}).get("number"),
        }
    except Exception as e:
        logger.error(f"Failed to get Notion task {page_id}: {e}")
        return None
