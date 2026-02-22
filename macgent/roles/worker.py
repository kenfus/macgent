"""Worker role — executes tasks with Stakeholder ping-pong."""

import logging
from macgent.roles.base import BaseRole
from macgent.prompts.role_prompts import WORKER_PLAN_PROMPT, WORKER_LEARN_PROMPT

logger = logging.getLogger("macgent.roles.worker")


class WorkerRole(BaseRole):
    role_name = "worker"

    def tick(self):
        """Called each heartbeat: check messages, claim and run next task."""
        logger.info("Worker tick starting")
        self.db.log("worker", "tick_start")

        # Check for manager pings
        pings = self.db.get_unread_messages("worker")
        for msg in pings:
            if msg["from_role"] == "manager":
                print(f"  Worker: Got ping from Manager: {msg['content'][:80]}")
        self.db.mark_messages_read("worker")

        # Pick next pending task
        task = self.db.next_pending_task()
        if not task:
            print("  Worker: No pending tasks")
            self.db.log("worker", "no_tasks")
            return

        print(f"  Worker: Claiming task #{task['id']}: {task['title']}")
        self.run_task(task["id"])

        self.db.log("worker", "tick_done")

    def run_task(self, task_id: int):
        """Full task lifecycle: clarify → execute → submit for review."""
        task = self.db.get_task(task_id)
        if not task:
            logger.error(f"Task #{task_id} not found")
            return

        self.db.log("worker", "task_claimed", task["title"], task_id)

        # Phase A: Clarification with Stakeholder
        approved = self._clarify_with_stakeholder(task)
        if not approved:
            print(f"  Worker: Clarification failed for task #{task_id}, escalating")
            self.db.update_task(task_id, status="escalated",
                                escalation="Clarification ping-pong exceeded max rounds")
            self.db.log("worker", "escalated", "Clarification failed", task_id)
            return

        # Phase B: Execute
        self.db.update_task(task_id, status="in_progress")
        print(f"  Worker: Executing task #{task_id}")

        result = self._execute_task(task)
        self.db.update_task(task_id, result=result, status="review")
        self.memory.record_turn(self.db, task_id, "worker", "result", result)
        self.db.log("worker", "submitted_review", result[:100], task_id)

        # Phase C: Wait for Stakeholder review and handle feedback
        self._handle_review_loop(task_id, task, result)

    def _clarify_with_stakeholder(self, task: dict) -> bool:
        """Send plan to Stakeholder, ping-pong until approved."""
        task_id = task["id"]
        max_rounds = self.config.max_ping_pong_rounds

        # Generate initial plan
        system = self.get_system_prompt(task_id, task["description"])
        prompt = WORKER_PLAN_PROMPT.format(
            task_title=task["title"],
            task_description=task["description"],
        )

        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=1024,
            )
        except Exception as e:
            logger.error(f"Plan generation failed: {e}")
            return True  # Skip clarification on LLM failure, try to execute anyway

        data = self.parse_json(response)
        plan = data.get("plan", response) if data else response

        self.memory.record_turn(self.db, task_id, "worker", "plan", plan)
        self.db.update_task(task_id, status="clarifying")

        for round_num in range(1, max_rounds + 1):
            print(f"  Worker: Clarification round {round_num}/{max_rounds}")

            # Send plan to Stakeholder
            self.db.send_message("worker", "stakeholder", task_id,
                                 f"PLAN:\n{plan}")
            self.db.update_task(task_id, ping_pong_round=round_num)

            # Get Stakeholder's response (call directly instead of via messages)
            from macgent.roles.stakeholder import StakeholderRole
            stakeholder = StakeholderRole(self.config, self.db, self.memory)
            sh_response = stakeholder.review_plan(task)

            if sh_response is None:
                # Stakeholder LLM failed, just proceed
                print("  Worker: Stakeholder unavailable, proceeding with plan")
                return True

            self.memory.record_turn(self.db, task_id, "stakeholder", "feedback",
                                     str(sh_response))

            if sh_response.get("approved", False):
                print(f"  Worker: Plan approved by Stakeholder")
                return True

            # Incorporate feedback
            feedback = sh_response.get("feedback", "No specific feedback")
            print(f"  Worker: Stakeholder feedback: {feedback[:80]}")

            # Revise plan
            try:
                revise_response = self.call_llm(
                    [{"role": "user", "content": f"Revise your plan based on feedback:\n{feedback}\n\nOriginal plan:\n{plan}"}],
                    system=system, max_tokens=1024,
                )
                data = self.parse_json(revise_response)
                plan = data.get("plan", revise_response) if data else revise_response
                self.memory.record_turn(self.db, task_id, "worker", "plan", plan)
            except Exception as e:
                logger.error(f"Plan revision failed: {e}")
                return True  # Proceed anyway

        return False  # Max rounds exceeded

    def _execute_task(self, task: dict) -> str:
        """Execute the task using the existing Agent."""
        from macgent.agent import Agent

        agent = Agent(self.config)
        state = agent.run(task["description"])

        # Build result summary
        parts = [f"Status: {state.status}", f"Steps: {len(state.steps)}"]
        if state.steps:
            last = state.steps[-1]
            if last.action.type == "done":
                parts.append(f"Summary: {last.action.params.get('summary', 'completed')}")
            elif last.action_result:
                parts.append(f"Last result: {last.action_result[:200]}")

        return "\n".join(parts)

    def _handle_review_loop(self, task_id: int, task: dict, result: str):
        """Handle Stakeholder review with retry loop."""
        max_rounds = self.config.max_ping_pong_rounds

        for round_num in range(1, max_rounds + 1):
            print(f"  Worker: Review round {round_num}/{max_rounds}")

            # Get Stakeholder review
            from macgent.roles.stakeholder import StakeholderRole
            stakeholder = StakeholderRole(self.config, self.db, self.memory)

            task_fresh = self.db.get_task(task_id)
            review = stakeholder.review_result(task_fresh)

            if review is None:
                print("  Worker: Stakeholder unavailable, marking completed")
                self.db.update_task(task_id, status="completed")
                self._learn_from_task(task, result)
                return

            if review.get("escalate", False):
                print(f"  Worker: Stakeholder escalated to CEO")
                self.db.update_task(task_id, status="escalated",
                                     review_note=review.get("note", ""),
                                     escalation="Stakeholder escalated")
                self.db.log("worker", "escalated", review.get("note", ""), task_id)
                return

            if review.get("approved", False):
                print(f"  Worker: Task approved! {review.get('note', '')[:60]}")
                self.db.update_task(task_id, status="completed",
                                     review_note=review.get("note", ""))
                self.db.log("worker", "completed", review.get("note", ""), task_id)
                self._learn_from_task(task, result)
                return

            # Rejected — retry with feedback
            feedback = review.get("note", "No specific feedback")
            print(f"  Worker: Rejected — {feedback[:80]}")
            self.db.update_task(task_id, status="in_progress",
                                 review_note=feedback,
                                 ping_pong_round=round_num)
            self.memory.record_turn(self.db, task_id, "stakeholder", "feedback", feedback)

            # Re-execute with feedback context
            task["description"] += f"\n\nPREVIOUS FEEDBACK: {feedback}"
            result = self._execute_task(task)
            self.db.update_task(task_id, result=result, status="review")

        # Max review rounds exceeded — escalate
        print(f"  Worker: Max review rounds exceeded, escalating")
        self.db.update_task(task_id, status="escalated",
                             escalation="Max review rounds exceeded")
        self.db.log("worker", "escalated", "Max review rounds", task_id)

    def _learn_from_task(self, task: dict, result: str):
        """Extract and store a lesson from the completed task."""
        system = self.get_system_prompt()
        prompt = WORKER_LEARN_PROMPT.format(
            task_title=task["title"],
            result=result[:500],
            steps="(see above)",
        )

        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=256,
            )
            data = self.parse_json(response)
            if data and "lesson" in data:
                self.memory.remember(
                    self.db, "worker", data["lesson"],
                    category=data.get("category", "lesson"),
                    task_id=task.get("id"),
                )
                print(f"  Worker: Learned — {data['lesson'][:60]}")
        except Exception as e:
            logger.debug(f"Learning failed (non-critical): {e}")
