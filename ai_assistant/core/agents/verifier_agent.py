"""
verifier_agent.py — Verifies that an executed step succeeded.

Uses pygetwindow for window detection and the FeedbackLoop for screenshot
verification where available.  Each intent type has a dedicated check; for
unknown intents the agent assumes success so the orchestrator can continue.

Public API
----------
VerifierAgent.run(task) -> AgentResult
    ``result.success`` reflects whether the step is confirmed to have
    completed.  ``result.output`` is a human-readable PASS/FAIL message.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.agents.base_agent import AgentResult, AgentTask, BaseAgent
from utils.helpers import setup_logger

logger = setup_logger(__name__)


class VerifierAgent(BaseAgent):
    """Checks whether the previous execution step actually succeeded.

    Verification strategy by intent
    --------------------------------
    ``open_app``
        Delegates to ``FeedbackLoop.verify_app_opened``.  Falls back to a
        naïve ``pygetwindow`` check if the FeedbackLoop import fails.

    ``create_file``
        Checks the file at ``task.context['target']`` exists on disk.

    ``execute_command``
        Inspects ``task.context['exec_result']`` for a leading ``'✅'``.

    *(anything else)*
        Returns ``success=True`` (optimistic default — avoids blocking the
        orchestrator when no specific check is implemented).
    """

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Verifier"

    @property
    def role(self) -> str:
        return "Verifies step success"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def run(self, task: AgentTask) -> AgentResult:
        """Verify the outcome of the step described by *task*.

        Parameters
        ----------
        task:
            Relevant context keys:

            - ``'intent'``      : determines which verification strategy to use
            - ``'target'``      : file path or app name being verified
            - ``'exec_result'`` : string output from the executor (used for
                                  ``execute_command`` verification)

        Returns
        -------
        AgentResult
            ``success`` is ``True`` when verification passes.
        """
        intent: str = task.context.get("intent", "")
        target: str = task.context.get("target", "")

        logger.info("[Verifier] Checking intent=%r target=%r", intent, target)

        verified: bool = False

        try:
            if intent == "open_app":
                verified = await self._verify_open_app(target)

            elif intent == "create_file":
                verified = self._verify_file_exists(target)

            elif intent == "execute_command":
                exec_result: str = task.context.get("exec_result", "")
                verified = exec_result.startswith("✅")
                logger.debug(
                    "[Verifier] execute_command check: exec_result=%r → %s",
                    exec_result[:80],
                    verified,
                )

            else:
                # Optimistic default for unsupported intent types
                logger.debug(
                    "[Verifier] No specific check for intent=%r — assuming success.",
                    intent,
                )
                verified = True

        except Exception as exc:
            logger.error("[Verifier] Verification error: %s", exc)
            # Don't crash the orchestrator; treat as soft-fail
            verified = False

        status_label = "PASS" if verified else "FAIL"
        output = f"Verification: {status_label} for {task.goal[:80]}"
        logger.info("[Verifier] %s", output)

        return AgentResult(
            success=verified,
            output=output,
            agent_name=self.name,
        )

    # ------------------------------------------------------------------
    # Private verification helpers
    # ------------------------------------------------------------------

    async def _verify_open_app(self, target: str) -> bool:
        """Return True when *target* app/window is detected on-screen."""
        # Preferred path: use FeedbackLoop for screenshot-based verification
        try:
            from automation.feedback_loop import FeedbackLoop  # type: ignore

            loop = FeedbackLoop()
            result: bool = await loop.verify_app_opened(target)
            logger.debug("[Verifier] FeedbackLoop.verify_app_opened(%r) → %s", target, result)
            return result

        except ImportError:
            logger.warning(
                "[Verifier] FeedbackLoop not available — falling back to pygetwindow."
            )

        # Fallback: check for any open window whose title contains the target
        try:
            import pygetwindow as gw  # type: ignore

            needle = target.lower()
            windows = gw.getAllTitles()
            found = any(needle in title.lower() for title in windows if title)
            logger.debug(
                "[Verifier] pygetwindow check for %r → %s (%d windows scanned)",
                target,
                found,
                len(windows),
            )
            return found

        except Exception as exc:
            logger.error("[Verifier] pygetwindow error: %s", exc)
            return False

    @staticmethod
    def _verify_file_exists(target: str) -> bool:
        """Return True when *target* resolves to an existing file on disk."""
        if not target:
            logger.warning("[Verifier] create_file intent but target is empty.")
            return False

        path = Path(target).expanduser()
        exists = path.exists() and path.is_file()
        logger.debug("[Verifier] File check %r → %s", str(path), exists)
        return exists
