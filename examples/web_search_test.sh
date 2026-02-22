#!/bin/bash
# Simple DuckDuckGo web search test — no auth, no complex SPA, reliable baseline
cd "$(dirname "$0")/.."
uv run macgent 'Go to duckduckgo.com. Search for "best hotels in Basel Switzerland 2026". Wait for the results to load. List the top 5 search result titles and their URLs from the results page. Then report done with the list.'
