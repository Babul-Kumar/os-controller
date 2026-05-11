"""
ScreenReader — gives Botbro the ability to "see" the PC screen.
Takes screenshots, crops regions, reads text (OCR), and finds UI elements.
"""
import os
import time
import pyautogui
import cv2
import numpy as np
from PIL import Image
from utils.helpers import setup_logger

logger = setup_logger(__name__)

SCREENSHOTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "screenshots"
)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class ScreenReader:
    @staticmethod
    def take_screenshot(filename: str = "screen.png") -> str:
        """Take a full screenshot and save it. Returns the path."""
        path = os.path.join(SCREENSHOTS_DIR, filename)
        screenshot = pyautogui.screenshot()
        screenshot.save(path)
        logger.info(f"Screenshot saved: {path}")
        return path

    @staticmethod
    def get_screen_as_array() -> np.ndarray:
        """Capture the screen as a NumPy array (BGR for OpenCV)."""
        screenshot = pyautogui.screenshot()
        return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    @staticmethod
    def find_element_on_screen(template_path: str, confidence: float = 0.8):
        """
        Find a UI element on screen by matching a template image.
        Returns (x, y) center of the element, or None.
        """
        if not os.path.exists(template_path):
            logger.error(f"Template not found: {template_path}")
            return None

        screen = ScreenReader.get_screen_as_array()
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= confidence:
            h, w = template.shape[:2]
            cx = max_loc[0] + w // 2
            cy = max_loc[1] + h // 2
            logger.info(f"Found element at ({cx}, {cy}) with confidence {max_val:.2f}")
            return (cx, cy)
        else:
            logger.warning(f"Element not found (best match: {max_val:.2f})")
            return None

    @staticmethod
    def describe_screen() -> dict:
        """
        Take a screenshot and return basic info about the current screen state.
        """
        screen = ScreenReader.get_screen_as_array()
        h, w = screen.shape[:2]

        # Get dominant colors (simple approach)
        resized = cv2.resize(screen, (50, 50))
        avg_color = resized.mean(axis=(0, 1)).astype(int)  # BGR

        # Check if the screen is mostly light or dark
        brightness = int(avg_color.mean())
        mode = "dark" if brightness < 128 else "light"

        info = {
            "resolution": f"{w}x{h}",
            "brightness": brightness,
            "mode": mode,
            "avg_color_bgr": avg_color.tolist(),
        }
        logger.info(f"Screen described: {info}")
        return info

    @staticmethod
    def read_text_from_region(x: int, y: int, w: int, h: int) -> str:
        """
        Attempt to read text from a specific region using pytesseract (if installed).
        Falls back to a message if pytesseract is not available.
        """
        try:
            import pytesseract
            screen = ScreenReader.get_screen_as_array()
            region = screen[y:y + h, x:x + w]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            text = pytesseract.image_to_string(gray).strip()
            logger.info(f"OCR result: {text[:80]}")
            return text
        except ImportError:
            return "⚠️ pytesseract not installed. Install it for screen text reading."
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return ""

    @staticmethod
    def click_element(template_path: str, confidence: float = 0.8) -> bool:
        """Find an element on screen and click it."""
        loc = ScreenReader.find_element_on_screen(template_path, confidence)
        if loc:
            pyautogui.click(loc[0], loc[1])
            logger.info(f"Clicked element at {loc}")
            return True
        return False
