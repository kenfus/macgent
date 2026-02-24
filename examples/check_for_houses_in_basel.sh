#!/bin/bash
# Browse the web and find houses for sale in Basel, Switzerland.
cd "$(dirname "$0")/.."
uv run macgent 'Find at least 5 houses for sale in Basel, Switzerland. They should have at least 4.5 rooms, less than 1.3 Million CHF and be either in Bruderholz or Münchenstein. For each listing include: address or neighbourhood, price in CHF, size (m2 or rooms), and a link. When you have 5 or more, call done with the full list.'
