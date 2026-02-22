"""Email monitor — checks macOS Mail for new emails since last check."""

import logging
from datetime import datetime

logger = logging.getLogger("macgent.monitors.email")


class EmailMonitor:
    source_name = "email"

    def check(self, db) -> list[dict]:
        """Check for new emails since last check. Returns list of email dicts."""
        from macgent.actions.mail_actions import read_inbox

        state = db.get_monitor_state(self.source_name)
        last_check = state["last_check"] if state else None

        # Read recent emails
        raw = read_inbox(limit=10)
        if raw.startswith("Could not read mail") or raw.startswith("No emails"):
            logger.info(f"Email check: {raw.strip()}")
            db.set_monitor_state(self.source_name, datetime.now().isoformat())
            return []

        # Parse the email list
        emails = self._parse_inbox(raw)

        # Update last check time
        db.set_monitor_state(self.source_name, datetime.now().isoformat())

        if not emails:
            return []

        # If first run, return all. Otherwise filter by date.
        if last_check is None:
            logger.info(f"First email check, found {len(emails)} emails")
            return emails

        # On subsequent runs, only return unread emails
        new_emails = [e for e in emails if e.get("status") == "unread"]
        logger.info(f"Email check: {len(new_emails)} new unread emails")
        return new_emails

    def _parse_inbox(self, raw: str) -> list[dict]:
        """Parse the output of read_inbox into structured dicts."""
        emails = []
        current = {}
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                if current:
                    emails.append(current)
                    current = {}
                continue

            # "1. [unread] From: sender@example.com"
            if line[0].isdigit() and ". [" in line:
                if current:
                    emails.append(current)
                parts = line.split(". [", 1)
                current = {"number": int(parts[0])}
                rest = parts[1]
                status_end = rest.find("]")
                current["status"] = rest[:status_end]
                from_part = rest[status_end + 1:].strip()
                if from_part.startswith("From: "):
                    current["from"] = from_part[6:]
            elif line.startswith("Subject: "):
                current["subject"] = line[9:]
            elif line.startswith("Date: "):
                current["date"] = line[6:]

        if current:
            emails.append(current)

        return emails
