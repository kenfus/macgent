#!/bin/bash
# Open Google Sheets and add hotel data
cd "$(dirname "$0")/.."
uv run macgent 'Go to sheets.google.com. Create a new blank spreadsheet. In cell A1 type "Hotel Name", press Tab, type "Price", press Tab, type "Rating", press Tab, type "Location". Press Return. Then type "Hotel Schweizerhof Basel", Tab, "180 CHF", Tab, "8.5", Tab, "Near train station". Press Return. Type "Novotel Basel City", Tab, "150 CHF", Tab, "8.2", Tab, "Near Novartis". Press Return. Type "ibis Basel Bahnhof", Tab, "95 CHF", Tab, "7.8", Tab, "At train station". Then report done.'
