#!/bin/bash
# Smoke test for captcha-like flow with primary agent-browser runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run macgent 'Open https://neal.fun/not-a-robot/ and attempt to pass the challenge. If blocked after one attempt, report blocked with reason and artifact path.'
