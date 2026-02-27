"""Brave Search API integration for fast web lookup without browser navigation."""

from __future__ import annotations

import json
from typing import Any

import httpx


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

    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

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
