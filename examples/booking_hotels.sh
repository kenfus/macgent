#!/bin/bash
# Search for hotels in Basel on booking.com, check-in March 15-16 2026
cd "$(dirname "$0")/.."
uv run macgent 'Search booking.com for hotels in Basel, Switzerland. Check-in March 15, check-out March 16, 2026, 1 adult. List the first 5 results with hotel name, price, and rating.'
