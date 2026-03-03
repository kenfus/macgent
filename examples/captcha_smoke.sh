#!/bin/bash
# Smoke test for captcha-like flow with primary agent-browser runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run macgent 'Open https://neal.fun/not-a-robot/ and try to solve level 1 and 2.'
