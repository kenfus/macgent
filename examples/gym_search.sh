#!/bin/bash
# Find nearby gyms with reviews
cd "$(dirname "$0")/.."
uv run macgent 'Find the closest gyms near Güterstrasse 149 in Basel, Switzerland. List the top 5 results with name, address, rating, and a short summary of reviews.'
