# Skill: Brave Search

## Type
Core

## Purpose
Perform web search via Brave Search API directly (no browser navigation needed) for fast lookup tasks.

## Actions / Usage

```json
{"type": "brave_search", "params": {"query": "best hotels in Basel", "count": 5}}
```

Optional params:
- `count` (1-20, default 5)
- `country` (e.g. `us`, `ch`)
- `search_lang` (e.g. `en`, `de`)
- `safesearch` (`off`, `moderate`, `strict`)
- `freshness` (e.g. `pd`, `pw`, `pm`)

## Constraints

- Requires `BRAVE_SEARCH_API_KEY`.
- Use this before browser navigation for generic web research tasks.

## Failure / Escalation

Returns explicit API errors for missing key, bad request, rate limits, or provider failure.
