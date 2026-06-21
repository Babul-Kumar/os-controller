"""
browser_agent.py — LLM-driven browser automation agent.

Converts natural language web goals into Selenium step sequences.

Pipeline:
  Goal (str) → Ollama decomposition → List[BrowserStep] → Selenium execution
  → Screenshot verification → Success | Retry
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _SELENIUM_AVAILABLE = True
except ImportError:
    _SELENIUM_AVAILABLE = False
    logger.warning(
        "selenium not installed. BrowserAgent will be non-functional. "
        "Install with: pip install selenium"
    )

try:
    from webdriver_manager.chrome import ChromeDriverManager

    _WDM_AVAILABLE = True
except ImportError:
    _WDM_AVAILABLE = False
    logger.warning(
        "webdriver_manager not installed. ChromeDriver must be on PATH. "
        "Install with: pip install webdriver-manager"
    )

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# Valid browser action names
VALID_ACTIONS = frozenset(
    {
        "navigate",
        "click_text",
        "click_selector",
        "type_into",
        "wait_for",
        "scrape_text",
        "scroll_down",
        "press_key",
        "screenshot",
    }
)


@dataclass
class BrowserStep:
    """
    A single atomic browser automation step.

    Attributes:
        action:      The action type (one of VALID_ACTIONS).
        selector:    CSS selector or XPath used by click/type/wait actions.
        value:       A URL, key name, text to type, or other action-specific value.
        description: Human-readable description of what this step does.
        timeout:     Max seconds to wait for elements before raising an error.
    """

    action: str
    selector: str = ""
    value: str = ""
    description: str = ""
    timeout: int = 10


@dataclass
class BrowserResult:
    """
    The outcome of executing a sequence of BrowserSteps.

    Attributes:
        success:         True if all steps completed without a fatal error.
        steps_completed: Number of steps that ran successfully.
        total_steps:     Total number of planned steps.
        output:          Concatenated text scraped during execution.
        screenshots:     Absolute paths of any screenshots taken.
        error:           Human-readable error message if success is False.
    """

    success: bool
    steps_completed: int
    total_steps: int
    output: str
    screenshots: List[str]
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Ollama prompt template
# ---------------------------------------------------------------------------

_BROWSER_PLANNER_PROMPT = """\
You are a browser automation planner. Convert this web goal into JSON steps.
Goal: {goal}
Return ONLY a JSON array of steps, each with: action, selector, value, description
Available actions: navigate, click_text, click_selector, type_into, wait_for, scrape_text, scroll_down, press_key
Example for 'search Python jobs on LinkedIn':
[
  {{"action": "navigate", "value": "https://linkedin.com/jobs", "description": "Go to LinkedIn Jobs"}},
  {{"action": "click_selector", "selector": "input[aria-label='Search by title']", "value": "", "description": "Click search box"}},
  {{"action": "type_into", "selector": "input[aria-label='Search by title']", "value": "Python developer", "description": "Type job title"}},
  {{"action": "press_key", "value": "RETURN", "description": "Submit search"}}
]
"""


# ---------------------------------------------------------------------------
# BrowserAgent
# ---------------------------------------------------------------------------


class BrowserAgent:
    """
    LLM-powered browser automation agent.

    Usage:
        agent = BrowserAgent()
        result = agent.plan_and_execute("Search Hacker News for AI news")
        print(result)
        agent.close()
    """

    def __init__(self) -> None:
        """Lazy-initialise the Selenium driver (None until first use)."""
        self.driver: Optional[object] = None  # webdriver.Chrome | None

        # Resolve the screenshots directory relative to this file's package root
        _here = Path(__file__).resolve().parent.parent
        self._screenshots_dir: Path = _here / "screenshots" / "browser"
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "BrowserAgent created. Screenshots directory: %s", self._screenshots_dir
        )

    # ------------------------------------------------------------------
    # Driver management
    # ------------------------------------------------------------------

    def _init_driver(self) -> None:
        """
        Initialise a Chrome WebDriver instance if not already running.

        Uses webdriver_manager when available so the correct ChromeDriver
        version is downloaded automatically. Falls back to expecting
        chromedriver on PATH otherwise.
        """
        if self.driver is not None:
            return  # already initialised

        if not _SELENIUM_AVAILABLE:
            raise RuntimeError(
                "selenium is not installed. "
                "Run: pip install selenium webdriver-manager"
            )

        try:
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            options.add_argument("--start-maximized")
            # Keep browser open after the script exits so the user can inspect results
            options.add_experimental_option("detach", True)

            if _WDM_AVAILABLE:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                # Rely on chromedriver being available on PATH
                self.driver = webdriver.Chrome(options=options)

            self.driver.implicitly_wait(10)
            logger.info("Chrome WebDriver initialised successfully.")

        except Exception as exc:
            logger.error("Failed to initialise ChromeDriver: %s", exc)
            self.driver = None
            raise

    def close(self) -> None:
        """Quit the WebDriver and release resources."""
        if self.driver is not None:
            try:
                self.driver.quit()
                logger.info("Chrome WebDriver closed.")
            except Exception as exc:
                logger.error("Error closing WebDriver: %s", exc)
            finally:
                self.driver = None

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def plan_steps(self, goal: str) -> List[BrowserStep]:
        """
        Ask Ollama to decompose a natural language goal into BrowserSteps.

        Args:
            goal: Plain English description of what to achieve in the browser.

        Returns:
            A list of BrowserStep objects. Falls back to a minimal
            Google-search plan if Ollama is unavailable or returns
            unparseable JSON.
        """
        # Import here to avoid circular imports at module load time
        try:
            from services.ollama_service import call_ollama  # type: ignore
        except ImportError:
            logger.warning("ollama_service not importable; using fallback plan.")
            return self._fallback_plan(goal)

        prompt = _BROWSER_PLANNER_PROMPT.format(goal=goal)
        logger.info("Requesting browser plan from Ollama for goal: %s", goal)

        raw_response: Optional[str] = call_ollama(prompt)

        if not raw_response:
            logger.warning("Ollama returned empty response; using fallback plan.")
            return self._fallback_plan(goal)

        return self._parse_steps(raw_response, goal)

    def _parse_steps(self, raw: str, goal: str) -> List[BrowserStep]:
        """
        Parse a raw Ollama response into a list of BrowserStep objects.

        Handles common LLM quirks: markdown fences, extra prose before/after
        the JSON array, and missing optional fields.

        Args:
            raw:  The raw string returned by Ollama.
            goal: The original goal, used for fallback logging.

        Returns:
            Parsed BrowserStep list, or the fallback plan on failure.
        """
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            # Remove first and last fence lines
            cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        # Extract the JSON array portion (find first '[' to last ']')
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1:
            logger.warning(
                "No JSON array found in Ollama response; using fallback plan.\n"
                "Raw response: %s",
                raw[:300],
            )
            return self._fallback_plan(goal)

        json_str = cleaned[start : end + 1]

        try:
            raw_steps: list = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error (%s); using fallback plan.", exc)
            return self._fallback_plan(goal)

        steps: List[BrowserStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            action = item.get("action", "").strip()
            if action not in VALID_ACTIONS:
                logger.warning("Unknown action '%s' from Ollama — skipping step.", action)
                continue
            steps.append(
                BrowserStep(
                    action=action,
                    selector=item.get("selector", ""),
                    value=item.get("value", ""),
                    description=item.get("description", ""),
                    timeout=int(item.get("timeout", 10)),
                )
            )

        if not steps:
            logger.warning("Ollama plan had no valid steps; using fallback plan.")
            return self._fallback_plan(goal)

        logger.info("Parsed %d browser steps from Ollama.", len(steps))
        return steps

    @staticmethod
    def _fallback_plan(goal: str) -> List[BrowserStep]:
        """
        Minimal two-step fallback: navigate to Google and search for the goal.

        This is returned whenever Ollama is unavailable or returns bad JSON.
        """
        logger.info("Using fallback Google-search plan for goal: %s", goal)
        return [
            BrowserStep(
                action="navigate",
                value="https://www.google.com",
                description="Open Google (fallback plan)",
            ),
            BrowserStep(
                action="type_into",
                selector="textarea[name='q'], input[name='q']",
                value=goal,
                description=f"Search Google for: {goal}",
            ),
            BrowserStep(
                action="press_key",
                value="RETURN",
                description="Submit search",
            ),
        ]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_steps(self, steps: List[BrowserStep]) -> BrowserResult:
        """
        Execute a list of BrowserSteps sequentially.

        A screenshot is taken after every *navigate*, *click_*, and
        *press_key* step to give a visual audit trail.

        Args:
            steps: The planned sequence of browser actions.

        Returns:
            A BrowserResult summarising what happened.
        """
        screenshots: List[str] = []
        collected_output: List[str] = []
        steps_completed = 0

        try:
            self._init_driver()
        except RuntimeError as exc:
            return BrowserResult(
                success=False,
                steps_completed=0,
                total_steps=len(steps),
                output="",
                screenshots=[],
                error=str(exc),
            )

        for idx, step in enumerate(steps):
            logger.info(
                "Step %d/%d [%s]: %s",
                idx + 1,
                len(steps),
                step.action,
                step.description or step.value or step.selector,
            )
            try:
                text_output = self._dispatch_step(step)
                if text_output:
                    collected_output.append(text_output)

                # Take a screenshot after visually-meaningful steps
                if step.action in ("navigate", "click_text", "click_selector", "press_key"):
                    shot = self._take_screenshot(f"step_{idx + 1}_{step.action}")
                    if shot:
                        screenshots.append(shot)

                steps_completed += 1

            except Exception as exc:
                logger.error(
                    "Step %d failed (%s): %s", idx + 1, step.action, exc
                )
                # Take a failure screenshot for diagnostics
                shot = self._take_screenshot(f"step_{idx + 1}_ERROR")
                if shot:
                    screenshots.append(shot)

                return BrowserResult(
                    success=False,
                    steps_completed=steps_completed,
                    total_steps=len(steps),
                    output="\n".join(collected_output),
                    screenshots=screenshots,
                    error=f"Step {idx + 1} ({step.action}) failed: {exc}",
                )

        return BrowserResult(
            success=True,
            steps_completed=steps_completed,
            total_steps=len(steps),
            output="\n".join(collected_output),
            screenshots=screenshots,
            error=None,
        )

    def _dispatch_step(self, step: BrowserStep) -> Optional[str]:
        """
        Route a BrowserStep to the appropriate private handler.

        Returns scraped text for *scrape_text* steps; None for all others.
        """
        action = step.action
        if action == "navigate":
            self._do_navigate(step.value)
        elif action == "click_text":
            self._do_click_text(step.value)
        elif action == "click_selector":
            self._do_click_selector(step.selector, step.timeout)
        elif action == "type_into":
            self._do_type_into(step.selector, step.value, step.timeout)
        elif action == "wait_for":
            self._do_wait_for(step.selector, step.timeout)
        elif action == "scrape_text":
            return self._do_scrape_text(step.selector, step.timeout)
        elif action == "scroll_down":
            self._do_scroll_down()
        elif action == "press_key":
            self._do_press_key(step.value)
        elif action == "screenshot":
            path = self._take_screenshot("explicit_step")
            if path:
                logger.info("Screenshot saved: %s", path)
        else:
            logger.warning("Unknown action '%s' — skipping.", action)
        return None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def plan_and_execute(self, goal: str) -> str:
        """
        Plan and execute a natural language browser goal end-to-end.

        This is the primary public API for this class.

        Args:
            goal: What to achieve in the browser, in plain English.

        Returns:
            A human-readable result string describing what happened.
        """
        if not _SELENIUM_AVAILABLE:
            return (
                "Browser automation is unavailable because selenium is not installed.\n"
                "To enable it, run:\n"
                "  pip install selenium webdriver-manager"
            )

        logger.info("BrowserAgent.plan_and_execute called with goal: %s", goal)

        # 1. Plan
        steps = self.plan_steps(goal)
        logger.info("Plan contains %d steps.", len(steps))

        # 2. Execute
        result = self.execute_steps(steps)

        # 3. Format result
        return self._format_result(goal, result)

    @staticmethod
    def _format_result(goal: str, result: BrowserResult) -> str:
        """Convert a BrowserResult into a user-readable string."""
        status = "✅ SUCCESS" if result.success else "❌ FAILED"
        lines = [
            f"{status} — Goal: {goal}",
            f"Steps completed: {result.steps_completed}/{result.total_steps}",
        ]
        if result.output:
            lines.append(f"Scraped text:\n{result.output}")
        if result.screenshots:
            lines.append(
                "Screenshots: " + ", ".join(os.path.basename(s) for s in result.screenshots)
            )
        if result.error:
            lines.append(f"Error: {result.error}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private step handlers
    # ------------------------------------------------------------------

    def _do_navigate(self, url: str) -> None:
        """Navigate the browser to *url*, prepending https:// if needed."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        logger.debug("Navigating to: %s", url)
        self.driver.get(url)
        # Brief pause to allow the page to start loading
        time.sleep(1)

    def _do_click_text(self, text: str) -> None:
        """
        Click the first visible element whose text contains *text*.

        Uses a broad XPath so it works for links, buttons, and spans.
        """
        logger.debug("Clicking element with text: %s", text)
        elements = self.driver.find_elements(
            By.XPATH, f'//*[contains(text(), "{text}")]'
        )
        for el in elements:
            if el.is_displayed():
                el.click()
                time.sleep(0.5)
                return
        raise RuntimeError(
            f"No visible element found containing text '{text}'"
        )

    def _do_click_selector(self, selector: str, timeout: int = 10) -> None:
        """Click the element matching *selector*, waiting up to *timeout* seconds."""
        logger.debug("Clicking selector: %s", selector)
        wait = WebDriverWait(self.driver, timeout)
        el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        el.click()
        time.sleep(0.5)

    def _do_type_into(self, selector: str, value: str, timeout: int = 10) -> None:
        """
        Clear and type *value* into the element matching *selector*.

        Supports comma-separated selectors as a fallback chain so the agent
        can handle variant HTML structures (e.g. both <textarea> and <input>).
        """
        logger.debug("Typing '%s' into selector: %s", value, selector)
        wait = WebDriverWait(self.driver, timeout)

        # Try each selector in the comma-separated list until one resolves
        selectors = [s.strip() for s in selector.split(",")]
        el = None
        for sel in selectors:
            try:
                el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, sel)))
                break
            except Exception:
                continue

        if el is None:
            raise RuntimeError(f"No element found for selector(s): {selector}")

        el.clear()
        el.send_keys(value)
        time.sleep(0.3)

    def _do_wait_for(self, selector: str, timeout: int = 10) -> None:
        """Wait until the element matching *selector* is visible."""
        logger.debug("Waiting for selector: %s (timeout=%ds)", selector, timeout)
        wait = WebDriverWait(self.driver, timeout)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))

    def _do_scrape_text(self, selector: str, timeout: int = 10) -> str:
        """
        Return the inner text of all elements matching *selector*.

        If *selector* is empty or '*', returns the full page body text.
        """
        logger.debug("Scraping text from selector: %s", selector or "<body>")
        if not selector or selector == "*":
            el = self.driver.find_element(By.TAG_NAME, "body")
            return el.text[:2000]  # cap to avoid massive output

        wait = WebDriverWait(self.driver, timeout)
        try:
            el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
            return el.text
        except Exception:
            # Fall back to all matching elements
            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
            return "\n".join(e.text for e in elements if e.text.strip())

    def _do_scroll_down(self) -> None:
        """Scroll the page down by one viewport height."""
        logger.debug("Scrolling down.")
        self.driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(0.5)

    def _do_press_key(self, key_name: str) -> None:
        """
        Send a keyboard key to the currently focused element.

        *key_name* should be the name of a selenium Keys attribute
        (e.g. 'RETURN', 'TAB', 'ESCAPE').
        """
        logger.debug("Pressing key: %s", key_name)
        key_value = getattr(Keys, key_name.upper(), key_name)
        focused = self.driver.switch_to.active_element
        focused.send_keys(key_value)
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Screenshot helper
    # ------------------------------------------------------------------

    def _take_screenshot(self, label: str) -> Optional[str]:
        """
        Save a PNG screenshot to the screenshots directory.

        Args:
            label: A short descriptive label embedded in the filename.

        Returns:
            Absolute path of the saved file, or None on failure.
        """
        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}_{label}.png"
        path = self._screenshots_dir / filename
        try:
            self.driver.save_screenshot(str(path))
            logger.debug("Screenshot saved: %s", path)
            return str(path)
        except Exception as exc:
            logger.warning("Could not save screenshot '%s': %s", label, exc)
            return None
