"""
orchestrator.py — Coordinates all agents to execute complex multi-step tasks.

For a high-level goal like 'Create a Flask portfolio website':
  1. PlannerAgent  — breaks the goal into ordered steps
  2. For each step:
       CoderAgent   — generates code when the step needs a file
       ExecutorAgent — runs the desktop action
       VerifierAgent — confirms the step succeeded
  3. Progress events are streamed to the GUI via EventBus
  4. On step failure: logs a warning and continues (no hard abort)

Public API
----------
AgentOrchestrator.run_complex_task(goal)    -> str
    Runs the full plan→code→execute→verify pipeline and returns a summary.

AgentOrchestrator.is_complex_task(goal)     -> bool  (static)
    Heuristic: returns True when a goal string likely requires multi-step work.
"""

from __future__ import annotations

import threading
from typing import List

from core.agents.base_agent import AgentTask
from core.agents.coder_agent import CoderAgent
from core.agents.executor_agent import ExecutorAgent
from core.agents.planner_agent import PlannerAgent
from core.agents.verifier_agent import VerifierAgent
from core.event_bus import EventBus
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# Keywords that suggest the user wants a multi-step workflow
_COMPLEX_KEYWORDS = (
    "create",
    "build",
    "set up",
    "make a",
    "develop",
    "generate project",
    "website",
    "application",
    "app",
)


class AgentOrchestrator:
    """Coordinates PlannerAgent → CoderAgent → ExecutorAgent → VerifierAgent.

    Thread safety
    -------------
    ``run_complex_task`` is guarded by ``_lock`` so that a second invocation
    triggered by the GUI while a task is already running is rejected with a
    clear message rather than causing interleaved agent calls.

    EventBus events emitted
    -----------------------
    ``'agent_progress'`` — dict with keys:
        - ``step``     : human-readable progress description
        - ``agent``    : name of the agent currently active
        - ``progress`` : float 0.0–1.0 (omitted for the initial planning event)
    """

    def __init__(self) -> None:
        self.planner  = PlannerAgent()
        self.coder    = CoderAgent()
        self.executor = ExecutorAgent()
        self.verifier = VerifierAgent()

        self._lock       = threading.Lock()
        self._is_running = False

        logger.info("[Orchestrator] Initialized with agents: %s", [
            self.planner.name, self.coder.name,
            self.executor.name, self.verifier.name,
        ])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_complex_task(self, goal: str) -> str:
        """Execute a high-level *goal* using the full agent pipeline.

        Parameters
        ----------
        goal:
            Natural-language description of what to accomplish, e.g.
            ``'Create a Flask portfolio website'``.

        Returns
        -------
        str
            A formatted summary of every step's outcome.

        Notes
        -----
        - A step that fails verification does **not** abort the run; the
          orchestrator emits a warning event and moves to the next step.
        - The method is not re-entrant: if called while already running it
          returns an error string immediately.
        """
        # Guard against concurrent runs
        with self._lock:
            if self._is_running:
                logger.warning("[Orchestrator] Already running — rejected concurrent task.")
                return "⚠️ A task is already running. Please wait for it to finish."
            self._is_running = True

        try:
            return await self._execute(goal)
        finally:
            with self._lock:
                self._is_running = False

    @staticmethod
    def is_complex_task(goal: str) -> bool:
        """Return True when *goal* likely requires multi-step orchestration.

        Parameters
        ----------
        goal:
            Raw user input string.

        Examples
        --------
        >>> AgentOrchestrator.is_complex_task("create a flask app")
        True
        >>> AgentOrchestrator.is_complex_task("what time is it?")
        False
        """
        lower_goal = goal.lower()
        return any(kw in lower_goal for kw in _COMPLEX_KEYWORDS)

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    async def _execute(self, goal: str) -> str:
        """Internal implementation of the full agent pipeline."""
        import time
        from core.metrics_store import get_store
        
        orch_start = time.perf_counter()
        orch_success = True
        orch_error = ""
        total_steps = 0

        try:
            # ----------------------------------------------------------------
            # 1. Plan
            # ----------------------------------------------------------------
            logger.info("[Orchestrator] Starting plan for: %r", goal[:100])
            await EventBus.emit("agent_progress", {"step": "Planning…", "agent": "Planner"})

            planner_start = time.perf_counter()
            plan_result = await self.planner.run(AgentTask(goal=goal))
            planner_lat = (time.perf_counter() - planner_start) * 1000.0
            
            steps = plan_result.next_tasks or []
            total_steps = len(steps)
            
            get_store().log_agent(
                agent_name="Planner",
                task_summary=goal[:100],
                success=plan_result.success,
                latency_ms=planner_lat,
                steps=total_steps,
                error_msg="" if plan_result.success else plan_result.output or "Planning failed"
            )

            if not plan_result.success or not plan_result.next_tasks:
                msg = f"Could not plan task: {goal}"
                logger.error("[Orchestrator] %s", msg)
                await EventBus.emit("agent_progress", {"step": msg, "agent": "Planner", "progress": 0.0})
                orch_success = False
                orch_error = msg
                return msg

            results: List[str] = []

            logger.info("[Orchestrator] Plan has %d step(s).", total_steps)

            # ----------------------------------------------------------------
            # 2. Execute each step
            # ----------------------------------------------------------------
            for i, step_task in enumerate(steps, start=1):
                progress_fraction = i / total_steps
                progress_msg = f"Step {i}/{total_steps}: {step_task.goal[:60]}"

                await EventBus.emit("agent_progress", {
                    "step":     progress_msg,
                    "agent":    "Executor",
                    "progress": progress_fraction,
                })
                logger.info("[Orchestrator] %s", progress_msg)

                # -- 2a. Generate code if the step needs a file ---------------
                if (
                    step_task.context.get("intent") == "create_file"
                    and not step_task.context.get("content", "").strip()
                ):
                    logger.info("[Orchestrator] Step %d needs code — invoking CoderAgent.", i)
                    coder_start = time.perf_counter()
                    code_result = await self.coder.run(step_task)
                    coder_lat = (time.perf_counter() - coder_start) * 1000.0
                    
                    get_store().log_agent(
                        agent_name="Coder",
                        task_summary=step_task.goal[:100],
                        success=code_result.success,
                        latency_ms=coder_lat,
                        steps=0,
                        error_msg="" if code_result.success else code_result.output or "Coding failed"
                    )
                    
                    if code_result.success:
                        step_task.context["content"] = code_result.artifacts.get("code", "")
                    else:
                        logger.warning(
                            "[Orchestrator] CoderAgent failed for step %d: %s",
                            i, code_result.output,
                        )

                # -- 2b. Execute ----------------------------------------------
                exec_start = time.perf_counter()
                exec_result = await self.executor.run(step_task)
                exec_lat = (time.perf_counter() - exec_start) * 1000.0
                
                get_store().log_agent(
                    agent_name="Executor",
                    task_summary=step_task.goal[:100],
                    success=exec_result.success,
                    latency_ms=exec_lat,
                    steps=0,
                    error_msg="" if exec_result.success else exec_result.output or "Execution failed"
                )
                
                step_task.context["exec_result"] = exec_result.output

                # -- 2c. Verify -----------------------------------------------
                verify_start = time.perf_counter()
                verify_result = await self.verifier.run(step_task)
                verify_lat = (time.perf_counter() - verify_start) * 1000.0
                
                get_store().log_agent(
                    agent_name="Verifier",
                    task_summary=step_task.goal[:100],
                    success=verify_result.success,
                    latency_ms=verify_lat,
                    steps=0,
                    error_msg="" if verify_result.success else verify_result.message or "Verification failed"
                )

                # -- 2d. Record outcome ---------------------------------------
                status_emoji = "✅" if verify_result.success else "⚠️"
                step_summary = (
                    f"{status_emoji} Step {i}: {step_task.goal[:50]} "
                    f"— {exec_result.output[:80]}"
                )
                results.append(step_summary)
                logger.info("[Orchestrator] %s", step_summary)

                if not verify_result.success:
                    orch_success = False  # Mark overall orchestrator run as failed/warned if any step fails verification
                    orch_error = f"Step {i} verification failed"
                    await EventBus.emit("agent_progress", {
                        "step":     f"Step {i} failed verification, continuing…",
                        "agent":    "Verifier",
                        "progress": progress_fraction,
                    })

            # ----------------------------------------------------------------
            # 3. Done
            # ----------------------------------------------------------------
            await EventBus.emit("agent_progress", {
                "step":     "Task complete!",
                "agent":    "Orchestrator",
                "progress": 1.0,
            })

            summary = f"Task completed: {goal}\n\n" + "\n".join(results)
            logger.info("[Orchestrator] Finished. %d step(s) executed.", total_steps)
            return summary
            
        except Exception as exc:
            orch_success = False
            orch_error = str(exc)
            raise
        finally:
            orch_lat = (time.perf_counter() - orch_start) * 1000.0
            try:
                get_store().log_agent(
                    agent_name="Orchestrator",
                    task_summary=goal[:100],
                    success=orch_success,
                    latency_ms=orch_lat,
                    steps=total_steps,
                    error_msg=orch_error
                )
            except Exception as store_exc:
                logger.error(f"Failed to log orchestrator agent metrics: {store_exc}")
