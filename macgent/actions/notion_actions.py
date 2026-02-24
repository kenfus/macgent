"""Generic Notion REST API wrapper.

Thin layer — no status maps, no property knowledge, no schema opinions.
The agent learns the board layout during bootstrap and stores it in
souls/skills/notion.md. This module just provides the plumbing.
"""

import logging
import httpx

logger = logging.getLogger("macgent.actions.notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _simplify_props(props: dict) -> dict:
    """Flatten Notion property objects into simple key-value pairs."""
    out = {}
    for name, prop in props.items():
        ptype = prop.get("type", "")
        if ptype == "title":
            parts = prop.get("title", [])
            out[name] = "".join(p.get("plain_text", "") for p in parts)
        elif ptype == "rich_text":
            parts = prop.get("rich_text", [])
            out[name] = "".join(p.get("plain_text", "") for p in parts)
        elif ptype in ("select", "status"):
            val = prop.get(ptype)
            out[name] = val.get("name", "") if val else ""
        elif ptype == "multi_select":
            out[name] = [o.get("name", "") for o in prop.get("multi_select", [])]
        elif ptype == "number":
            out[name] = prop.get("number")
        elif ptype == "checkbox":
            out[name] = prop.get("checkbox", False)
        elif ptype == "date":
            d = prop.get("date")
            out[name] = d.get("start", "") if d else ""
        elif ptype == "url":
            out[name] = prop.get("url", "")
        else:
            out[name] = f"<{ptype}>"
    return out


def _simplify_page(page: dict) -> dict:
    """Convert a Notion page into a flat, readable dict."""
    result = {"page_id": page["id"]}
    result["last_edited_time"] = page.get("last_edited_time", "")
    result.update(_simplify_props(page.get("properties", {})))
    return result


# ── Generic CRUD ──


def notion_query(
    token: str,
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 50,
) -> list[dict]:
    """Query a Notion database. Returns list of simplified page dicts."""
    if not token or not database_id:
        return []

    body: dict = {"page_size": page_size}
    if filter:
        body["filter"] = filter
    if sorts:
        body["sorts"] = sorts

    try:
        resp = httpx.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json=body,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error(f"Notion query failed ({resp.status_code}): {resp.text[:500]}")
            return []
        return [_simplify_page(p) for p in resp.json().get("results", [])]
    except Exception as e:
        logger.error(f"Notion query error: {e}")
        return []


def notion_get(token: str, page_id: str) -> dict | None:
    """Get a single Notion page. Returns simplified dict or None."""
    if not token or not page_id:
        return None
    try:
        resp = httpx.get(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        return _simplify_page(resp.json())
    except Exception as e:
        logger.error(f"Notion get page {page_id}: {e}")
        return None


def notion_update(token: str, page_id: str, properties: dict) -> bool:
    """Update a Notion page's properties. Caller builds the raw Notion properties dict."""
    if not token or not page_id or not properties:
        return False
    try:
        resp = httpx.patch(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": properties},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Notion update page {page_id}: {e}")
        return False


def notion_create(token: str, database_id: str, properties: dict) -> str | None:
    """Create a Notion page. Caller builds the raw properties dict. Returns page_id."""
    if not token or not database_id:
        return None
    try:
        resp = httpx.post(
            f"{NOTION_API}/pages",
            headers=_headers(token),
            json={"parent": {"database_id": database_id}, "properties": properties},
            timeout=10,
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]
        logger.info(f"Created Notion page: {page_id}")
        return page_id
    except Exception as e:
        logger.error(f"Notion create page: {e}")
        return None


def notion_schema(token: str, database_id: str) -> str:
    """Get database schema as human-readable text. Used during bootstrap."""
    if not token or not database_id:
        return "ERROR: Notion not configured"
    try:
        resp = httpx.get(
            f"{NOTION_API}/databases/{database_id}",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        db_title = "".join(
            t.get("plain_text", "") for t in data.get("title", [])
        )
        props = data.get("properties", {})

        lines = [f"Database: {db_title}", f"ID: {database_id}", ""]
        lines.append("Properties:")
        for name, prop in props.items():
            ptype = prop.get("type", "unknown")
            detail = ""
            if ptype in ("select", "status"):
                options = prop.get(ptype, {}).get("options", [])
                names = [o["name"] for o in options]
                detail = f" -> options: {names}"
                if ptype == "status":
                    groups = prop.get("status", {}).get("groups", [])
                    if groups:
                        group_info = []
                        for g in groups:
                            gname = g["name"]
                            gids = g.get("option_ids", [])
                            gopts = [o["name"] for o in options if o["id"] in gids]
                            group_info.append(f"{gname}: {gopts}")
                        detail += f"\n    groups: {group_info}"
            elif ptype == "multi_select":
                options = prop.get("multi_select", {}).get("options", [])
                names = [o["name"] for o in options]
                detail = f" -> options: {names}"
            lines.append(f"  - {name} ({ptype}){detail}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Notion schema error: {e}")
        return f"ERROR: {e}"
