"""Stakeholder role — quality review, approve/reject/escalate."""

import logging
from macgent.roles.base import BaseRole
from macgent.prompts.role_prompts import STAKEHOLDER_CLARIFY_PROMPT, STAKEHOLDER_REVIEW_PROMPT

logger = logging.getLogger("macgent.roles.stakeholder")


class StakeholderRole(BaseRole):
    role_name = "stakeholder"

    def tick(self):
        """Called each heartbeat: review tasks in 'review' status."""
        logger.info("Stakeholder tick starting")
        self.db.log("stakeholder", "tick_start")

        review_tasks = self.db.get_review_tasks()
        if not review_tasks:
            print("  Stakeholder: No tasks to review")
            self.db.log("stakeholder", "no_reviews")
            return

        for task in review_tasks:
            print(f"  Stakeholder: Reviewing task #{task['id']}: {task['title']}")
            result = self.review_result(task)
            if result is None:
                continue

            if result.get("escalate", False):
                self.db.update_task(task["id"], status="escalated",
                                     review_note=result.get("note", ""),
                                     escalation="Stakeholder escalated")
                print(f"  Stakeholder: Escalated task #{task['id']}")
                self.db.log("stakeholder", "escalated", result.get("note", ""), task["id"])
            elif result.get("approved", False):
                self.db.update_task(task["id"], status="completed",
                                     review_note=result.get("note", ""))
                print(f"  Stakeholder: Approved task #{task['id']}")
                self.db.log("stakeholder", "approved", result.get("note", ""), task["id"])
            else:
                # Rejected — send back to worker
                feedback = result.get("note", "Needs improvement")
                self.db.update_task(task["id"], status="pending",
                                     review_note=feedback)
                self.db.send_message("stakeholder", "worker", task["id"],
                                     f"REVIEW FEEDBACK: {feedback}")
                print(f"  Stakeholder: Rejected task #{task['id']}: {feedback[:60]}")
                self.db.log("stakeholder", "rejected", feedback[:100], task["id"])

        self.db.log("stakeholder", "tick_done")

    def review_plan(self, task: dict) -> dict | None:
        """Review a Worker's plan (clarification phase). Returns parsed response."""
        # Get the latest plan from messages
        messages = self.db.get_task_messages(task["id"])
        plan = ""
        for msg in reversed(messages):
            if msg["from_role"] == "worker" and msg["content"].startswith("PLAN:"):
                plan = msg["content"][5:].strip()
                break

        if not plan:
            # Check short-term memory
            turns = self.memory.get_short_term(self.db, task["id"], "worker")
            for t in reversed(turns):
                if t["type"] == "plan":
                    plan = t["content"]
                    break

        if not plan:
            return {"approved": True, "feedback": "No plan provided, proceed."}

        system = self.get_system_prompt(task["id"], task["description"])
        prompt = STAKEHOLDER_CLARIFY_PROMPT.format(
            task_title=task["title"],
            task_description=task["description"],
            plan=plan,
        )

        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=512,
            )
        except Exception as e:
            logger.error(f"Stakeholder clarify LLM failed: {e}")
            return None

        data = self.parse_json(response)
        if not data:
            logger.warning(f"Could not parse stakeholder response: {response[:200]}")
            return {"approved": True, "feedback": "Could not parse response, proceeding."}

        self.memory.record_turn(self.db, task["id"], "stakeholder", "feedback",
                                 str(data))
        self.db.log("stakeholder", "clarify_review",
                     f"approved={data.get('approved')}", task["id"])
        return data

    def review_result(self, task: dict) -> dict | None:
        """Review a Worker's completed result. Returns parsed response."""
        result = task.get("result", "No result submitted")

        system = self.get_system_prompt(task["id"], task["description"])
        prompt = STAKEHOLDER_REVIEW_PROMPT.format(
            task_title=task["title"],
            task_description=task["description"],
            result=result,
        )

        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=512,
            )
        except Exception as e:
            logger.error(f"Stakeholder review LLM failed: {e}")
            return None

        data = self.parse_json(response)
        if not data:
            logger.warning(f"Could not parse stakeholder review: {response[:200]}")
            return {"approved": True, "note": "Could not parse review, auto-approving."}

        self.memory.record_turn(self.db, task["id"], "stakeholder", "review",
                                 str(data))
        self.db.log("stakeholder", "result_review",
                     f"approved={data.get('approved')}", task["id"])
        return data
