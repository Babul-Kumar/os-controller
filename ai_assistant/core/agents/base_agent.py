"""
base_agent.py — Abstract base class for all Botbro specialized agents.

Each agent has a single responsibility:
  PlannerAgent   — breaks goals into ordered subtasks
  CoderAgent     — generates code/file content
  ExecutorAgent  — runs actions on the desktop
  VerifierAgent  — checks if a step succeeded

Public API
----------
AgentTask   : dataclass describing a unit of work to be performed
AgentResult : dataclass holding the outcome of a completed task
BaseAgent   : abstract class all concrete agents must subclass
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from utils.helpers import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class AgentTask:
    """Describes a single unit of work passed to an agent.

    Attributes
    ----------
    goal:        Human-readable description of what must be accomplished.
    context:     Arbitrary key-value metadata required by the agent
                 (e.g. ``intent``, ``target``, ``content``, ``language``).
    constraints: Optional strings that restrict how the agent may act
                 (e.g. "do not overwrite existing files").
    parent_id:   ``task_id`` of the AgentTask that spawned this one (empty
                 string for top-level tasks).
    task_id:     Auto-generated 8-char hex identifier unique to this task.
    """

    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    parent_id: str = ""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        logger.debug("AgentTask created: id=%s goal=%r", self.task_id, self.goal[:80])


@dataclass
class AgentResult:
    """Holds the outcome produced by an agent after running a task.

    Attributes
    ----------
    success:    ``True`` if the agent believes the task was accomplished.
    output:     Human-readable summary or error message.
    artifacts:  Named outputs produced (e.g. ``{'code': '...', 'filename': 'app.py'}``).
    next_tasks: Follow-up ``AgentTask`` objects that should be dispatched next
                (populated mainly by ``PlannerAgent``).
    agent_name: Name of the agent that produced this result.
    """

    success: bool
    output: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    next_tasks: List[AgentTask] = field(default_factory=list)
    agent_name: str = ""

    def __post_init__(self) -> None:
        status = "OK" if self.success else "FAIL"
        logger.debug(
            "AgentResult[%s] %s — %s",
            self.agent_name or "?",
            status,
            self.output[:120],
        )


# ---------------------------------------------------------------------------
# Abstract base agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract superclass for every Botbro agent.

    Subclasses must implement:
    - ``name``  (property) — short human-readable label
    - ``role``  (property) — one-line description of what the agent does
    - ``run``   (async method) — execute a task and return an AgentResult

    Usage
    -----
    All agents are expected to be stateless with respect to individual tasks:
    any persistent state (model name, executor reference, etc.) is stored as
    instance attributes set up in ``__init__``.
    """

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``'Planner'``."""

    @property
    @abstractmethod
    def role(self) -> str:
        """One-line description, e.g. ``'Decomposes goals into subtasks'``."""

    @abstractmethod
    async def run(self, task: AgentTask) -> AgentResult:
        """Execute *task* and return an :class:`AgentResult`.

        Parameters
        ----------
        task:
            The unit of work this agent should process.

        Returns
        -------
        AgentResult
            Always returns an :class:`AgentResult` — never raises.  Errors
            should be captured and reported via ``AgentResult(success=False,
            output='...')``.
        """

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _ok(
        self,
        output: str,
        artifacts: Dict[str, Any] | None = None,
        next_tasks: List[AgentTask] | None = None,
    ) -> AgentResult:
        """Convenience factory for a successful result."""
        return AgentResult(
            success=True,
            output=output,
            artifacts=artifacts or {},
            next_tasks=next_tasks or [],
            agent_name=self.name,
        )

    def _fail(self, output: str) -> AgentResult:
        """Convenience factory for a failed result."""
        logger.error("[%s] Task failed: %s", self.name, output)
        return AgentResult(
            success=False,
            output=output,
            agent_name=self.name,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
