"""
ScreenReader — gives Botbro the ability to "see" the PC screen.
Takes screenshots, crops regions, reads text (OCR), and finds UI elements.

Phase 1 additions
-----------------
- read_full_screen_text()     — OCR the entire screen → str
- find_button_by_text(text)   — locate a labelled button via OCR → (x, y) or None
- find_dialog_text()          — detect common dialog patterns → str or None
- list_visible_windows()      — all non-empty window titles via pygetwindow
- get_active_window_title()   — currently focused window title
"""

import os
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
from PIL import Image

from utils.helpers import setup_logger

# ---------------------------------------------------------------------------
# Optional OCR dependency — degrade gracefully if pytesseract is not present
# ---------------------------------------------------------------------------
try:
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

logger = setup_logger(__name__)

SCREENSHOTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "screenshots"
)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class ScreenReader:
    # ------------------------------------------------------------------
    # ── Original methods (unchanged) ──────────────────────────────────
    # ------------------------------------------------------------------

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
    def find_element_on_screen(
        template_path: str, confidence: float = 0.8
    ) -> Optional[Tuple[int, int]]:
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
            import pytesseract as _pt
            import time as _time
            from core.metrics_store import get_store
            ocr_start = _time.perf_counter()
            screen = ScreenReader.get_screen_as_array()
            region = screen[y:y + h, x:x + w]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            text = _pt.image_to_string(gray).strip()
            ocr_lat = (_time.perf_counter() - ocr_start) * 1000.0
            
            try:
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=len(text),
                    latency_ms=ocr_lat,
                    confidence=1.0,
                    success=True
                )
            except Exception as store_exc:
                logger.error(f"Failed to log OCR metrics: {store_exc}")

            logger.info(f"OCR result: {text[:80]}")
            return text
        except ImportError:
            return "⚠️ pytesseract not installed. Install it for screen text reading."
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            try:
                from core.metrics_store import get_store
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=0,
                    latency_ms=0.0,
                    confidence=0.0,
                    success=False
                )
            except Exception:
                pass
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

    # ------------------------------------------------------------------
    # ── Phase 1 additions ─────────────────────────────────────────────
    # ------------------------------------------------------------------

    @staticmethod
    def read_full_screen_text() -> str:
        """
        OCR the entire screen and return all recognised text as a single string.

        Requires pytesseract to be installed.  Returns an empty string and
        logs a warning when OCR is unavailable.

        Returns
        -------
        str
            Full OCR output from the current screen, or ``""`` on failure.
        """
        if not _OCR_AVAILABLE:
            logger.warning(
                "[ScreenReader] read_full_screen_text: pytesseract not available"
            )
            return ""

        try:
            import time as _time
            from core.metrics_store import get_store
            ocr_start = _time.perf_counter()
            img = pyautogui.screenshot()
            text: str = pytesseract.image_to_string(img).strip()
            ocr_lat = (_time.perf_counter() - ocr_start) * 1000.0
            
            try:
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=len(text),
                    latency_ms=ocr_lat,
                    confidence=1.0,
                    success=True
                )
            except Exception as store_exc:
                logger.error(f"Failed to log OCR metrics: {store_exc}")

            logger.info(
                f"[ScreenReader] read_full_screen_text: "
                f"{len(text)} chars extracted"
            )
            return text
        except Exception as exc:
            logger.error(f"[ScreenReader] read_full_screen_text failed: {exc}")
            try:
                from core.metrics_store import get_store
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=0,
                    latency_ms=0.0,
                    confidence=0.0,
                    success=False
                )
            except Exception:
                pass
            return ""

    @staticmethod
    def find_button_by_text(text: str) -> Optional[Tuple[int, int]]:
        """
        OCR the screen and return the pixel centre (x, y) of the first word
        or token that matches *text* (case-insensitive, partial match).

        Useful for dynamically clicking on labelled buttons whose position
        changes between runs.

        Parameters
        ----------
        text:
            The button label to search for (e.g. ``"OK"``, ``"Save"``)

        Returns
        -------
        Optional[Tuple[int, int]]
            Screen coordinates of the matched token centre, or ``None`` when
            OCR is unavailable or *text* is not found.
        """
        if not _OCR_AVAILABLE:
            logger.warning(
                "[ScreenReader] find_button_by_text: pytesseract not available"
            )
            return None

        text_lower = text.lower()
        try:
            import time as _time
            from core.metrics_store import get_store
            ocr_start = _time.perf_counter()
            img = pyautogui.screenshot()
            data = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
            )
            ocr_lat = (_time.perf_counter() - ocr_start) * 1000.0
            
            ocr_words = [str(w) for w in data.get("text", []) if str(w).strip()]
            text_content = " ".join(ocr_words)
            success_found = any(text_lower in w.lower() for w in ocr_words)
            
            try:
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=len(text_content),
                    latency_ms=ocr_lat,
                    confidence=1.0 if success_found else 0.0,
                    success=True
                )
            except Exception as store_exc:
                logger.error(f"Failed to log OCR metrics: {store_exc}")
        except Exception as exc:
            logger.error(f"[ScreenReader] find_button_by_text OCR failed: {exc}")
            try:
                from core.metrics_store import get_store
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=0,
                    latency_ms=0.0,
                    confidence=0.0,
                    success=False
                )
            except Exception:
                pass
            return None

        n_boxes = len(data["level"])

        for i in range(n_boxes):
            word = str(data["text"][i]).strip()
            if not word:
                continue
            if text_lower in word.lower():
                x = data["left"][i]
                y = data["top"][i]
                w = data["width"][i]
                h = data["height"][i]
                cx = x + w // 2
                cy = y + h // 2
                logger.info(
                    f"[ScreenReader] Button {text!r} found at ({cx}, {cy})"
                )
                return (cx, cy)

        logger.info(f"[ScreenReader] Button {text!r} not found on screen")
        return None

    @staticmethod
    def find_dialog_text() -> Optional[str]:
        """
        OCR the screen and detect common Windows dialog box patterns.

        Recognised patterns (checked in priority order):

        =========  ========================================================
        Return     Trigger keywords
        =========  ========================================================
        'ok_cancel'  Both "ok" and "cancel" visible on screen
        'yes_no'     Both "yes" and "no" visible on screen
        'error'      "error", "failed", or "exception" visible on screen
        'info'       "information" or "notice" visible on screen
        =========  ========================================================

        Returns ``None`` when OCR is unavailable or no pattern matches.

        Returns
        -------
        Optional[str]
            One of ``'ok_cancel'``, ``'yes_no'``, ``'error'``, ``'info'``,
            or ``None``.
        """
        if not _OCR_AVAILABLE:
            logger.warning(
                "[ScreenReader] find_dialog_text: pytesseract not available"
            )
            return None

        try:
            import time as _time
            from core.metrics_store import get_store
            ocr_start = _time.perf_counter()
            img = pyautogui.screenshot()
            raw_text: str = pytesseract.image_to_string(img).lower()
            ocr_lat = (_time.perf_counter() - ocr_start) * 1000.0
            
            try:
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=len(raw_text),
                    latency_ms=ocr_lat,
                    confidence=1.0,
                    success=True
                )
            except Exception as store_exc:
                logger.error(f"Failed to log OCR metrics: {store_exc}")
        except Exception as exc:
            logger.error(f"[ScreenReader] find_dialog_text OCR failed: {exc}")
            try:
                from core.metrics_store import get_store
                get_store().log_ocr(
                    engine="pytesseract",
                    image_path="",
                    char_count=0,
                    latency_ms=0.0,
                    confidence=0.0,
                    success=False
                )
            except Exception:
                pass
            return None

        # Priority-ordered pattern matching
        if "ok" in raw_text and "cancel" in raw_text:
            dialog_type = "ok_cancel"
        elif "yes" in raw_text and "no" in raw_text:
            dialog_type = "yes_no"
        elif any(kw in raw_text for kw in ("error", "failed", "exception")):
            dialog_type = "error"
        elif any(kw in raw_text for kw in ("information", "notice")):
            dialog_type = "info"
        else:
            dialog_type = None

        logger.info(
            f"[ScreenReader] find_dialog_text: detected={dialog_type!r}"
        )
        return dialog_type

    @staticmethod
    def list_visible_windows() -> List[str]:
        """
        Return a list of all currently visible (non-empty-title) window titles
        obtained via pygetwindow.

        Returns
        -------
        List[str]
            Alphabetically sorted list of non-blank window titles.
        """
        try:
            titles = [t for t in gw.getAllTitles() if t.strip()]
            titles_sorted = sorted(set(titles))
            logger.info(
                f"[ScreenReader] list_visible_windows: "
                f"{len(titles_sorted)} windows found"
            )
            return titles_sorted
        except Exception as exc:
            logger.error(f"[ScreenReader] list_visible_windows failed: {exc}")
            return []

    @staticmethod
    def get_active_window_title() -> str:
        """
        Return the title of the currently focused (active) window.

        Uses pygetwindow's ``getActiveWindow()`` where available and falls
        back to an empty string on error.

        Returns
        -------
        str
            Active window title, or ``""`` if it cannot be determined.
        """
        try:
            active_win = gw.getActiveWindow()
            title: str = active_win.title if active_win else ""
            logger.info(
                f"[ScreenReader] get_active_window_title: {title!r}"
            )
            return title
        except Exception as exc:
            logger.error(f"[ScreenReader] get_active_window_title failed: {exc}")
            return ""
