"""Worker role — placeholder. Task execution is handled by the manager agent."""

from __future__ import annotations

import logging

from macgent.roles.base import BaseRole

logger = logging.getLogger("macgent.roles.worker")


class WorkerRole(BaseRole):
    role_name = "worker"

    def tick(self):
        pass
