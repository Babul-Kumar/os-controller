"""
coder_agent.py — Generates code and file content using the local LLM.

Short-circuits to the pre-provided content when ``task.context['content']``
is already populated, avoiding an unnecessary Ollama round-trip.

Public API
----------
CoderAgent.run(task) -> AgentResult
    ``result.artifacts`` contains:
      - ``'code'``     : the generated (or pre-provided) source text
      - ``'filename'`` : the suggested output filename
"""

from __future__ import annotations

from core.agents.base_agent import AgentResult, AgentTask, BaseAgent
from services.ollama_service import call_ollama
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_CODE_PROMPT = (
    "Generate complete, working code for: {goal}\n"
    "Language/framework: {language}\n"
    "Return ONLY the code, no explanation, no markdown fences."
)


class CoderAgent(BaseAgent):
    """Produces source-code for a given goal via the local Ollama LLM.

    If the task's context already contains a ``'content'`` key the agent
    returns that content immediately without calling the model, which avoids
    redundant inference when the ``PlannerAgent`` has already embedded the
    file body inside the plan.
    """

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Coder"

    @property
    def role(self) -> str:
        return "Generates code and content"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def run(self, task: AgentTask) -> AgentResult:
        """Generate or pass-through code for *task.goal*.

        Parameters
        ----------
        task:
            The coding task.  Relevant context keys:

            - ``'content'``  : pre-existing code (skip LLM if present)
            - ``'language'`` : target language / framework (default: ``'Python'``)
            - ``'filename'`` : suggested output filename (default: ``'output.py'``)

        Returns
        -------
        AgentResult
            ``artifacts={'code': ..., 'filename': ...}`` on success.
        """
        filename: str = task.context.get("filename", task.context.get("target", "output.py"))
        language: str = task.context.get("language", "Python")

        # Fast-path: content already supplied (e.g. by PlannerAgent)
        pre_content: str = task.context.get("content", "").strip()
        if pre_content:
            logger.info(
                "[Coder] Using pre-supplied content for %r (%d chars)",
                filename,
                len(pre_content),
            )
            return self._ok(
                output=f"Used pre-supplied content for {filename}",
                artifacts={"code": pre_content, "filename": filename},
            )

        # LLM path: ask Ollama to generate the code
        prompt = _CODE_PROMPT.format(goal=task.goal, language=language)
        logger.info("[Coder] Requesting code from Ollama for: %r", task.goal[:100])

        try:
            generated_code: str = await call_ollama(prompt)
        except Exception as exc:
            logger.error("[Coder] Ollama call failed: %s", exc)
            return self._fail(f"Ollama error: {exc}")

        # Strip accidental markdown fences that some models include
        generated_code = _strip_fences(generated_code)

        logger.info("[Coder] Generated %d chars for %r", len(generated_code), filename)

        return self._ok(
            output=f"Generated code for {filename} ({len(generated_code)} chars)",
            artifacts={"code": generated_code, "filename": filename},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code-fence markers if present.

    Some models wrap their output in triple-backtick blocks even when asked
    not to.  This strips the first and last fence if detected.

    Examples
    --------
    >>> _strip_fences("```python\\nprint('hi')\\n```")
    "print('hi')"
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
