"""Brave Search API integration for fast web lookup without browser navigation."""

from __future__ import annotations

import json
import time
import logging
from typing import Any

import httpx

logger = logging.getLogger("macgent.brave_search")
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_START = 2.0
_BACKOFF_MULT = 2.0


def brave_web_search(
    api_key: str,
    query: str,
    api_base: str = "https://api.search.brave.com",
    count: int = 5,
    country: str | None = None,
    search_lang: str | None = None,
    safesearch: str = "moderate",
    freshness: str | None = None,
) -> dict[str, Any]:
    """Run a Brave web search and return normalized results."""
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured")
    if not query.strip():
        raise ValueError("query must not be empty")

    url = api_base.rstrip("/") + "/res/v1/web/search"
    params: dict[str, Any] = {
        "q": query,
        "count": max(1, min(int(count), 20)),
        "safesearch": safesearch,
    }
    if country:
        params["country"] = country
    if search_lang:
        params["search_lang"] = search_lang
    if freshness:
        params["freshness"] = freshness

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }

    backoff = _BACKOFF_START
    data = None
    for attempt in range(1, _MAX_RETRIES + 2):
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers, params=params)
        if resp.status_code in _RETRY_STATUSES and attempt <= _MAX_RETRIES:
            logger.info("brave_search status=%d, retrying in %.1fs (attempt %d/%d)",
                        resp.status_code, backoff, attempt, _MAX_RETRIES)
            time.sleep(backoff)
            backoff *= _BACKOFF_MULT
            continue
        resp.raise_for_status()
        data = resp.json()
        break
    if data is None:
        raise RuntimeError("brave_search failed after retries")

    raw_results = data.get("web", {}).get("results", [])
    results = []
    for item in raw_results:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "age": item.get("age", ""),
            }
        )

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


def brave_web_search_json(*args, **kwargs) -> str:
    """JSON wrapper to keep dispatcher return type simple."""
    return json.dumps(brave_web_search(*args, **kwargs), ensure_ascii=False)
