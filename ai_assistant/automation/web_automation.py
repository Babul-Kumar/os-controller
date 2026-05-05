from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import urllib.parse
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class WebAutomator:
    def __init__(self):
        self.driver = None

    def _init_driver(self):
        """Initialize the Chrome WebDriver if not already running."""
        if self.driver is None:
            try:
                chrome_options = Options()
                # Keep browser open after script finishes
                chrome_options.add_experimental_option("detach", True)
                
                # Note: Assuming standard webdriver usage. For production with undetected-chromedriver,
                # you would import undetected_chromedriver as uc and use uc.Chrome()
                self.driver = webdriver.Chrome(options=chrome_options)
                self.driver.implicitly_wait(10)
                logger.info("WebDriver initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize WebDriver: {e}")
                raise

    def open_website(self, url: str) -> str:
        """Open a specific URL."""
        try:
            # Ensure URL has http/https protocol
            if not url.startswith('http://') and not url.startswith('https://'):
                url = 'https://' + url
                
            self._init_driver()
            self.driver.get(url)
            return f"Opened website: {url}"
        except Exception as e:
            logger.error(f"Failed to open website {url}: {e}")
            return f"Failed to open website: {str(e)}"

    def search_google(self, query: str) -> str:
        """Perform a Google search."""
        try:
            self._init_driver()
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://www.google.com/search?q={encoded_query}"
            self.driver.get(search_url)
            return f"Searched Google for: '{query}'"
        except Exception as e:
            logger.error(f"Failed to search Google for '{query}': {e}")
            return f"Search failed: {str(e)}"

    def close_browser(self):
        """Close the browser if it's open."""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                return "Browser closed."
            except Exception as e:
                logger.error(f"Failed to close browser: {e}")
                return f"Failed to close browser: {str(e)}"
        return "No browser was open."
