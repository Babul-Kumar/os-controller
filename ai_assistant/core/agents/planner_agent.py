"""
planner_agent.py — Decomposes complex goals into ordered, executable subtasks.

Calls Ollama with a decomposition prompt to break high-level goals into
concrete steps that other agents can execute.

Public API
----------
PlannerAgent.run(task) -> AgentResult
    ``result.next_tasks`` contains the ordered list of :class:`AgentTask`
    objects ready for the orchestrator to dispatch to downstream agents.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from core.agents.base_agent import AgentResult, AgentTask, BaseAgent
from services.ollama_service import call_ollama
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_DECOMPOSITION_PROMPT = """\
You are a task decomposition expert. Break this goal into 3-7 concrete, executable steps.
Goal: {goal}
Context: {context}

Return ONLY a JSON array of steps (no markdown, no commentary):
[{{"step": 1, "action": "create_file", "description": "Create app.py", "target": "app.py", "content": "...", "intent": "create_file"}}]

Available intents: open_app, create_file, write_text, execute_command, web_search, draw_shape
Each step must be directly executable. Include full file content for create_file steps.
"""

# Fallback steps used when the LLM response cannot be parsed as JSON.
_FALLBACK_STEPS: List[Dict[str, Any]] = [
    {
        "step": 1,
        "action": "execute_command",
        "description": "Create project folder",
        "target": "project",
        "content": "",
        "intent": "execute_command",
    },
    {
        "step": 2,
        "action": "create_file",
        "description": "Create main entry-point",
        "target": "main.py",
        "content": "# Entry point\nprint('Hello, Botbro!')\n",
        "intent": "create_file",
    },
    {
        "step": 3,
        "action": "open_app",
        "description": "Open project in VS Code",
        "target": "vscode",
        "content": "",
        "intent": "open_app",
    },
]


class PlannerAgent(BaseAgent):
    """Breaks a high-level goal into a list of concrete :class:`AgentTask` objects.

    The agent sends a structured decomposition prompt to the local Ollama
    instance and parses the JSON array it returns.  If parsing fails (e.g. the
    model produces non-JSON text) a safe three-step fallback plan is used
    instead so the orchestrator always has *something* to execute.
    """

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Planner"

    @property
    def role(self) -> str:
        return "Decomposes goals into subtasks"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def run(self, task: AgentTask) -> AgentResult:
        """Decompose *task.goal* into an ordered sequence of sub-tasks.

        Parameters
        ----------
        task:
            Top-level task whose ``goal`` string will be decomposed.
            ``task.context`` is forwarded to the LLM for additional context.

        Returns
        -------
        AgentResult
            ``success=True`` with ``next_tasks`` populated when planning
            succeeded (even when the fallback plan is used).
            ``success=False`` only if the Ollama call itself raises.
        """
        prompt = _DECOMPOSITION_PROMPT.format(
            goal=task.goal,
            context=json.dumps(task.context, default=str),
        )

        # --- Call the LLM -----------------------------------------------
        try:
            logger.info("[Planner] Requesting decomposition for: %r", task.goal[:100])
            raw_response: str = await call_ollama(prompt)
            logger.debug("[Planner] Raw LLM response: %s", raw_response[:500])
        except Exception as exc:
            logger.error("[Planner] Ollama call failed: %s", exc)
            return self._fail(f"Ollama error: {exc}")

        # --- Parse JSON from the response --------------------------------
        steps = self._parse_steps(raw_response)

        if not steps:
            logger.warning(
                "[Planner] Could not parse LLM response — using fallback plan."
            )
            steps = _FALLBACK_STEPS

        # --- Convert dicts → AgentTasks ---------------------------------
        next_tasks = self._steps_to_tasks(steps, parent_id=task.task_id)

        logger.info("[Planner] Plan ready: %d step(s) for goal %r", len(next_tasks), task.goal[:60])

        return self._ok(
            output=f"Planned {len(next_tasks)} step(s)",
            next_tasks=next_tasks,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_steps(self, raw: str) -> List[Dict[str, Any]]:
        """Extract the first valid JSON array from *raw*.

        Tries progressively more lenient strategies:
        1. Direct ``json.loads`` on the full response.
        2. Regex extraction of the first ``[...]`` block.
        """
        # Strategy 1 — the response is already valid JSON
        try:
            data = json.loads(raw.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Strategy 2 — extract the first [...] block
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return []

    def _steps_to_tasks(
        self,
        steps: List[Dict[str, Any]],
        parent_id: str,
    ) -> List[AgentTask]:
        """Convert a list of step-dicts into :class:`AgentTask` objects."""
        tasks: List[AgentTask] = []
        for step in steps:
            if not isinstance(step, dict):
                continue

            intent = step.get("intent", "create_file")
            description = step.get("description", step.get("action", "unnamed step"))

            context: Dict[str, Any] = {
                "intent": intent,
                "target": step.get("target", ""),
                "content": step.get("content", ""),
                "step_number": step.get("step", len(tasks) + 1),
            }

            tasks.append(
                AgentTask(
                    goal=description,
                    context=context,
                    parent_id=parent_id,
                )
            )

        return tasks
