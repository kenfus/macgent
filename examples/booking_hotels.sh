#!/bin/bash
# Search for hotels near Novartis Campus Basel on booking.com
cd "$(dirname "$0")/.."
uv run macgent 'Go to booking.com. Search for hotels in Basel, Switzerland near the Novartis Campus and train station. Check in March 15, check out March 16, 2026, 1 adult. Search and list the hotel names, prices, and ratings from the results. Then report done with the list.'
