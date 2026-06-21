"""
executor_agent.py — Executes desktop actions using the CommandExecutor.

Bridges the agent layer to the existing ``CommandExecutor`` that knows how to
open applications, create files, run shell commands, etc.

Public API
----------
ExecutorAgent.run(task) -> AgentResult
    Translates ``task.context`` into an ``intent_data`` dict and delegates
    to ``CommandExecutor.execute_intent``.
"""

from __future__ import annotations

from core.agents.base_agent import AgentResult, AgentTask, BaseAgent
from core.executor import CommandExecutor
from utils.helpers import setup_logger

logger = setup_logger(__name__)


class ExecutorAgent(BaseAgent):
    """Runs desktop actions by forwarding intent data to :class:`CommandExecutor`.

    The mapping from an :class:`AgentTask` to an intent dict is intentionally
    simple: the ``intent``, ``target``, ``content``, and ``editor`` keys are
    lifted directly from ``task.context`` so that the ``PlannerAgent`` has full
    control over what the executor will do.

    Success detection
    -----------------
    ``CommandExecutor.execute_intent`` returns a human-readable string.  We
    treat the result as successful when it contains the emoji ``✅`` or the
    word ``"success"`` (case-insensitive).  All other output is treated as a
    failure worth surfacing to the verifier.
    """

    def __init__(self) -> None:
        # Instantiate the shared command executor
        self._executor = CommandExecutor()
        logger.debug("[Executor] CommandExecutor instantiated.")

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Executor"

    @property
    def role(self) -> str:
        return "Executes desktop actions"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def run(self, task: AgentTask) -> AgentResult:
        """Execute the desktop action described by *task*.

        Parameters
        ----------
        task:
            Relevant context keys:

            - ``'intent'``  : action type (e.g. ``'create_file'``, ``'open_app'``)
            - ``'target'``  : file path or application name
            - ``'content'`` : file body for ``create_file`` intents
            - ``'editor'``  : preferred editor (default: ``'vscode'``)

        Returns
        -------
        AgentResult
            ``success`` is ``True`` when the executor result contains ``'✅'``
            or ``'success'``.
        """
        intent_data = {
            "intent":  task.context.get("intent",  "create_file"),
            "target":  task.context.get("target",  ""),
            "content": task.context.get("content", ""),
            "editor":  task.context.get("editor",  "vscode"),
        }

        logger.info(
            "[Executor] Executing intent=%r target=%r",
            intent_data["intent"],
            intent_data["target"],
        )

        try:
            result: str = await self._executor.execute_intent(intent_data)
        except Exception as exc:
            logger.error("[Executor] execute_intent raised: %s", exc)
            return self._fail(f"Execution error: {exc}")

        succeeded = "✅" in result or "success" in result.lower()
        log_fn = logger.info if succeeded else logger.warning
        log_fn("[Executor] Result (success=%s): %s", succeeded, result[:200])

        return AgentResult(
            success=succeeded,
            output=result,
            agent_name=self.name,
        )
