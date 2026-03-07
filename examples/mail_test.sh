#!/bin/bash
# Read emails and send a test email
cd "$(dirname "$0")/.."
uv run macgent 'Read my recent emails from the inbox. Then send a test email to test@gmail.com with subject "Test from macgent" and body "Hello! This is an automated test email from macgent, the macOS automation agent. It works!" Then report done.'
