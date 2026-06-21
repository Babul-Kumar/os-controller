"""
web_automation.py — High-level web automation facade for Botbro.

Combines a direct Selenium driver for simple navigations and searches
with the AI-powered BrowserAgent for complex multi-step tasks expressed
in natural language.

Public API
----------
WebAutomator.open_website(url)         → str
WebAutomator.search_google(query)      → str
WebAutomator.close_browser()           → str
WebAutomator.execute_web_task(goal)    → str   # delegates to BrowserAgent
WebAutomator.search_linkedin_jobs(q)   → str
WebAutomator.search_kaggle(q)          → str
WebAutomator.open_github_repo(repo)    → str
WebAutomator.fill_form(url, fields)    → str
"""

import urllib.parse
import time
from typing import Dict

from utils.helpers import setup_logger
from automation.browser_agent import BrowserAgent  # Phase 2 AI agent

# Selenium imports — the same guard as browser_agent for consistency
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    _SELENIUM_AVAILABLE = True
except ImportError:
    _SELENIUM_AVAILABLE = False

logger = setup_logger(__name__)


class WebAutomator:
    """
    Facade for browser-based automation tasks.

    Provides:
    - Simple, self-contained methods that operate a dedicated Selenium driver
      (``open_website``, ``search_google``, ``close_browser``).
    - An AI-powered path (``execute_web_task`` and named shortcuts) that
      delegates to ``BrowserAgent`` for complex, multi-step web goals.

    The two drivers (WebAutomator's own driver and BrowserAgent's driver)
    are intentionally separate so quick navigations don't interfere with
    long-running agent sessions.
    """

    def __init__(self) -> None:
        # Own lightweight driver for simple page opens / searches
        self.driver = None

        # AI-powered agent for natural language web tasks
        self.agent = BrowserAgent()

        logger.info("WebAutomator initialised (BrowserAgent attached).")

    # ------------------------------------------------------------------
    # Internal driver management (simple tasks)
    # ------------------------------------------------------------------

    def _init_driver(self) -> None:
        """
        Initialise the lightweight Chrome WebDriver if not already running.

        This driver is used only by the simple helper methods
        (``open_website``, ``search_google``). It is kept separate from
        the BrowserAgent's driver so the two don't interfere.
        """
        if self.driver is not None:
            return

        if not _SELENIUM_AVAILABLE:
            raise RuntimeError(
                "selenium is not installed. "
                "Run: pip install selenium webdriver-manager"
            )

        try:
            chrome_options = Options()
            # Keep the browser open after the script finishes
            chrome_options.add_experimental_option("detach", True)
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(10)
            logger.info("WebAutomator: Chrome WebDriver initialised successfully.")
        except Exception as exc:
            logger.error("Failed to initialise WebDriver: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Simple navigation helpers (preserved from Phase 1)
    # ------------------------------------------------------------------

    def open_website(self, url: str) -> str:
        """
        Open a specific URL in the browser.

        Prepends ``https://`` if no protocol is given.

        Args:
            url: The web address to open.

        Returns:
            A confirmation or error string.
        """
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            self._init_driver()
            self.driver.get(url)
            logger.info("Opened website: %s", url)
            return f"Opened website: {url}"
        except Exception as exc:
            logger.error("Failed to open website %s: %s", url, exc)
            return f"Failed to open website: {exc}"

    def search_google(self, query: str) -> str:
        """
        Perform a Google search by navigating directly to the search URL.

        Args:
            query: The search terms.

        Returns:
            A confirmation or error string.
        """
        try:
            self._init_driver()
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://www.google.com/search?q={encoded_query}"
            self.driver.get(search_url)
            logger.info("Searched Google for: '%s'", query)
            return f"Searched Google for: '{query}'"
        except Exception as exc:
            logger.error("Failed to search Google for '%s': %s", query, exc)
            return f"Search failed: {exc}"

    def close_browser(self) -> str:
        """
        Close both the simple driver and the BrowserAgent's driver.

        Returns:
            A status string.
        """
        messages = []

        # Close the lightweight driver
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                messages.append("Simple browser closed.")
                logger.info("WebAutomator: simple WebDriver closed.")
            except Exception as exc:
                logger.error("Failed to close simple WebDriver: %s", exc)
                messages.append(f"Failed to close simple browser: {exc}")
        else:
            messages.append("No simple browser was open.")

        # Close the BrowserAgent driver
        try:
            self.agent.close()
            messages.append("BrowserAgent driver closed.")
        except Exception as exc:
            logger.warning("Error closing BrowserAgent driver: %s", exc)
            messages.append(f"BrowserAgent close warning: {exc}")

        return " | ".join(messages)

    # ------------------------------------------------------------------
    # AI-powered natural language web tasks (Phase 2)
    # ------------------------------------------------------------------

    def execute_web_task(self, goal: str) -> str:
        """
        Execute an arbitrary web task described in plain English.

        Delegates entirely to ``BrowserAgent.plan_and_execute``, which
        uses Ollama to decompose the goal into browser steps and then
        runs them sequentially with Selenium.

        Args:
            goal: A natural language description of the desired outcome,
                  e.g. "Find the latest Python release on python.org and
                  tell me its version number."

        Returns:
            A human-readable result string from BrowserAgent.
        """
        logger.info("execute_web_task called with goal: %s", goal)
        return self.agent.plan_and_execute(goal)

    # ------------------------------------------------------------------
    # Named shortcut methods (build goals, delegate to execute_web_task)
    # ------------------------------------------------------------------

    def search_linkedin_jobs(self, query: str) -> str:
        """
        Search LinkedIn Jobs for the given query and list 3 results.

        Args:
            query: Job title or keyword, e.g. "Python developer".

        Returns:
            Result string from BrowserAgent.
        """
        goal = f"Search for {query} jobs on LinkedIn and list 3 results"
        logger.info("search_linkedin_jobs: %s", goal)
        return self.execute_web_task(goal)

    def search_kaggle(self, query: str) -> str:
        """
        Search Kaggle for competitions matching *query*.

        Args:
            query: Search term, e.g. "image classification".

        Returns:
            Result string from BrowserAgent.
        """
        goal = f"Search Kaggle for {query} competitions"
        logger.info("search_kaggle: %s", goal)
        return self.execute_web_task(goal)

    def open_github_repo(self, repo: str) -> str:
        """
        Navigate directly to a GitHub repository.

        Args:
            repo: Repository path in ``owner/name`` format,
                  e.g. "openai/whisper".

        Returns:
            Result string from BrowserAgent.
        """
        goal = f"Open github.com/{repo}"
        logger.info("open_github_repo: %s", goal)
        return self.execute_web_task(goal)

    def fill_form(self, url: str, fields: Dict[str, str]) -> str:
        """
        Navigate to *url* and fill a form with the provided *fields*.

        Args:
            url:    The URL of the page containing the form.
            fields: A mapping of field labels / names to their desired
                    values, e.g. {"Name": "Alice", "Email": "a@b.com"}.

        Returns:
            Result string from BrowserAgent.
        """
        goal = f"Go to {url} and fill the form with {fields}"
        logger.info("fill_form: url=%s fields=%s", url, fields)
        return self.execute_web_task(goal)
