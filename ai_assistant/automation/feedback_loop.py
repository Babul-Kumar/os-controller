"""
feedback_loop.py — Screenshot-based action verification and retry system.

After every automation action (open app, write text, draw), Botbro takes a
screenshot to verify success. If verification fails, it retries up to max_retries.

Pipeline:
  Action → Screenshot → Verify (window/text/OCR) → Success | Retry
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Coroutine, List, Optional, Tuple, Any

import pyautogui
import pygetwindow as gw

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

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
# This file lives at: os-controller/ai_assistant/automation/feedback_loop.py
# BASE_DIR should point to:  os-controller/ai_assistant/
_THIS_FILE = Path(__file__).resolve()
BASE_DIR = _THIS_FILE.parent.parent          # ai_assistant/
SCREENSHOTS_DIR = BASE_DIR / "assets" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data-class for a single verification result
# ---------------------------------------------------------------------------
@dataclass
class VerificationResult:
    """Encapsulates the outcome of one verification attempt."""

    success: bool
    screenshot_path: str = ""
    detected_windows: List[str] = field(default_factory=list)
    ocr_text: str = ""
    confidence: float = 0.0
    message: str = ""

    def __str__(self) -> str:  # pragma: no cover
        status = "✅ PASS" if self.success else "❌ FAIL"
        return (
            f"{status} | conf={self.confidence:.2f} | "
            f"msg={self.message!r} | screenshot={self.screenshot_path!r}"
        )


# ---------------------------------------------------------------------------
# Main FeedbackLoop class
# ---------------------------------------------------------------------------
class FeedbackLoop:
    """
    Provides verification primitives that wrap every automation action with
    a screenshot-based feedback loop.

    Public API
    ----------
    verify_app_opened(app_name, timeout)
    verify_text_on_screen(expected_text, timeout)
    verify_window_has_content(window_title)
    retry_with_feedback(action_coro, verify_fn, max_retries, delay)
    take_verification_screenshot(label)
    find_text_on_screen(text)
    """

    # ------------------------------------------------------------------
    # Screenshot helpers
    # ------------------------------------------------------------------

    def take_verification_screenshot(self, label: str = "") -> str:
        """
        Capture a full-screen screenshot and persist it under assets/screenshots.

        Parameters
        ----------
        label:
            A short human-readable tag embedded in the filename so results
            are easy to find when debugging (e.g. 'notepad_opened').

        Returns
        -------
        str
            Absolute path to the saved PNG file.
        """
        timestamp = int(time.time() * 1000)
        safe_label = label.replace(" ", "_") if label else "check"
        filename = f"verify_{safe_label}_{timestamp}.png"
        path = SCREENSHOTS_DIR / filename

        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(str(path))
            logger.info(f"[FeedbackLoop] Verification screenshot saved: {path}")
        except Exception as exc:
            logger.error(f"[FeedbackLoop] Failed to save screenshot: {exc}")
            return ""

        return str(path)

    # ------------------------------------------------------------------
    # Window / app verification
    # ------------------------------------------------------------------

    def verify_app_opened(
        self,
        app_name: str,
        timeout: int = 8,
    ) -> VerificationResult:
        """
        Poll pygetwindow every 0.5 s for up to *timeout* seconds to confirm
        that a window whose title contains *app_name* (case-insensitive) has
        appeared on the desktop.

        Parameters
        ----------
        app_name:
            Partial name of the expected window title (e.g. 'Notepad').
        timeout:
            Maximum seconds to wait before declaring failure.

        Returns
        -------
        VerificationResult
        """
        app_name_lower = app_name.lower()
        deadline = time.monotonic() + timeout
        all_titles: List[str] = []

        logger.info(f"[FeedbackLoop] Waiting up to {timeout}s for window: {app_name!r}")

        while time.monotonic() < deadline:
            try:
                all_titles = [t for t in gw.getAllTitles() if t.strip()]
            except Exception as exc:
                logger.warning(f"[FeedbackLoop] pygetwindow error: {exc}")
                all_titles = []

            matching = [t for t in all_titles if app_name_lower in t.lower()]
            if matching:
                screenshot_path = self.take_verification_screenshot(
                    label=app_name.replace(" ", "_")
                )
                result = VerificationResult(
                    success=True,
                    screenshot_path=screenshot_path,
                    detected_windows=all_titles,
                    confidence=1.0,
                    message=f"Window found: {matching[0]!r}",
                )
                logger.info(f"[FeedbackLoop] {result}")
                return result

            time.sleep(0.5)

        # Timeout reached — window not detected
        result = VerificationResult(
            success=False,
            detected_windows=all_titles,
            confidence=0.0,
            message=f"Timeout after {timeout}s: no window matching {app_name!r}",
        )
        logger.info(f"[FeedbackLoop] {result}")
        return result

    def verify_window_has_content(self, window_title: str) -> VerificationResult:
        """
        Verify that a window with a title matching *window_title* exists AND
        has non-trivial dimensions (width > 100 px, height > 100 px).

        This catches cases where an app window exists in the task-bar but has
        been minimised or initialised with zero size.

        Parameters
        ----------
        window_title:
            Partial or full title of the target window.

        Returns
        -------
        VerificationResult
        """
        title_lower = window_title.lower()
        try:
            all_titles = [t for t in gw.getAllTitles() if t.strip()]
        except Exception as exc:
            logger.error(f"[FeedbackLoop] pygetwindow error: {exc}")
            return VerificationResult(
                success=False,
                message=f"pygetwindow error: {exc}",
            )

        matching_wins = [t for t in all_titles if title_lower in t.lower()]
        if not matching_wins:
            result = VerificationResult(
                success=False,
                detected_windows=all_titles,
                message=f"No window found matching {window_title!r}",
            )
            logger.info(f"[FeedbackLoop] {result}")
            return result

        # Attempt to retrieve size for the first matching window
        try:
            wins = gw.getWindowsWithTitle(matching_wins[0])
            if not wins:
                raise RuntimeError("getWindowsWithTitle returned empty list")
            win = wins[0]
            w, h = win.width, win.height

            if w > 100 and h > 100:
                result = VerificationResult(
                    success=True,
                    detected_windows=all_titles,
                    confidence=1.0,
                    message=(
                        f"Window {matching_wins[0]!r} has content "
                        f"({w}x{h} px)"
                    ),
                )
            else:
                result = VerificationResult(
                    success=False,
                    detected_windows=all_titles,
                    confidence=0.3,
                    message=(
                        f"Window {matching_wins[0]!r} too small "
                        f"({w}x{h} px) — may be minimised"
                    ),
                )
        except Exception as exc:
            logger.warning(
                f"[FeedbackLoop] Could not get window size for "
                f"{matching_wins[0]!r}: {exc}"
            )
            # Window title found but size check failed — treat as partial success
            result = VerificationResult(
                success=True,
                detected_windows=all_titles,
                confidence=0.6,
                message=f"Window {matching_wins[0]!r} found; size check skipped ({exc})",
            )

        logger.info(f"[FeedbackLoop] {result}")
        return result

    # ------------------------------------------------------------------
    # OCR / text verification
    # ------------------------------------------------------------------

    def verify_text_on_screen(
        self,
        expected_text: str,
        timeout: int = 5,
    ) -> VerificationResult:
        """
        Capture the screen and check whether *expected_text* appears anywhere
        in the OCR output (case-insensitive, partial match).

        Falls back to window-title matching via pygetwindow when pytesseract
        is not installed.

        Parameters
        ----------
        expected_text:
            The text string to search for.
        timeout:
            Seconds to retry OCR passes before giving up.

        Returns
        -------
        VerificationResult
        """
        expected_lower = expected_text.lower()
        deadline = time.monotonic() + timeout

        if not _OCR_AVAILABLE:
            # Graceful degradation: match against visible window titles
            logger.warning(
                "[FeedbackLoop] pytesseract not available — "
                "falling back to window-title matching"
            )
            try:
                all_titles = [t for t in gw.getAllTitles() if t.strip()]
            except Exception as exc:
                all_titles = []
                logger.error(f"[FeedbackLoop] pygetwindow error: {exc}")

            matching = [t for t in all_titles if expected_lower in t.lower()]
            success = bool(matching)
            result = VerificationResult(
                success=success,
                detected_windows=all_titles,
                confidence=0.5 if success else 0.0,
                message=(
                    f"(fallback) Window-title match for {expected_text!r}: "
                    f"{'found' if success else 'not found'}"
                ),
            )
            logger.info(f"[FeedbackLoop] {result}")
            return result

        # OCR path
        ocr_text = ""
        screenshot_path = ""
        while time.monotonic() < deadline:
            screenshot_path = self.take_verification_screenshot(
                label=f"ocr_{expected_text[:20].replace(' ', '_')}"
            )
            try:
                import time as _time
                from core.metrics_store import get_store
                ocr_start = _time.perf_counter()
                img = pyautogui.screenshot()
                ocr_text = pytesseract.image_to_string(img).strip()
                ocr_lat = (_time.perf_counter() - ocr_start) * 1000.0
                
                success_found = expected_lower in ocr_text.lower()
                try:
                    get_store().log_ocr(
                        engine="pytesseract",
                        image_path=screenshot_path,
                        char_count=len(ocr_text),
                        latency_ms=ocr_lat,
                        confidence=1.0 if success_found else 0.0,
                        success=True
                    )
                except Exception as store_exc:
                    logger.error(f"Failed to log OCR metrics: {store_exc}")
            except Exception as exc:
                logger.error(f"[FeedbackLoop] OCR error: {exc}")
                ocr_text = ""
                try:
                    get_store().log_ocr(
                        engine="pytesseract",
                        image_path=screenshot_path,
                        char_count=0,
                        latency_ms=0.0,
                        confidence=0.0,
                        success=False
                    )
                except Exception:
                    pass

            if expected_lower in ocr_text.lower():
                result = VerificationResult(
                    success=True,
                    screenshot_path=screenshot_path,
                    ocr_text=ocr_text,
                    confidence=1.0,
                    message=f"Text {expected_text!r} found on screen via OCR",
                )
                logger.info(f"[FeedbackLoop] {result}")
                return result

            time.sleep(0.75)

        result = VerificationResult(
            success=False,
            screenshot_path=screenshot_path,
            ocr_text=ocr_text,
            confidence=0.0,
            message=(
                f"Timeout after {timeout}s: "
                f"text {expected_text!r} not found on screen"
            ),
        )
        logger.info(f"[FeedbackLoop] {result}")
        return result

    def find_text_on_screen(self, text: str) -> Optional[Tuple[int, int]]:
        """
        OCR the full screen and return the (x, y) pixel-centre of the region
        containing *text*.  Useful for dynamically clicking on labels.

        Returns ``None`` when OCR is unavailable or the text cannot be found.

        Parameters
        ----------
        text:
            The string to locate on screen.

        Returns
        -------
        Optional[Tuple[int, int]]
            Screen coordinates of the text centre, or None.
        """
        if not _OCR_AVAILABLE:
            logger.warning(
                "[FeedbackLoop] find_text_on_screen: pytesseract not available"
            )
            return None

        text_lower = text.lower()
        try:
            import time as _time
            from core.metrics_store import get_store
            ocr_start = _time.perf_counter()
            img = pyautogui.screenshot()
            # image_to_data gives per-word bounding boxes with confidence scores
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
            logger.error(f"[FeedbackLoop] OCR data extraction failed: {exc}")
            try:
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
                # Bounding box
                x = data["left"][i]
                y = data["top"][i]
                w = data["width"][i]
                h = data["height"][i]
                cx = x + w // 2
                cy = y + h // 2
                logger.info(
                    f"[FeedbackLoop] Text {text!r} found at centre ({cx}, {cy})"
                )
                return (cx, cy)

        logger.info(f"[FeedbackLoop] Text {text!r} not found on screen")
        return None

    # ------------------------------------------------------------------
    # Retry orchestrator
    # ------------------------------------------------------------------

    async def retry_with_feedback(
        self,
        action_coro: Coroutine[Any, Any, Any],
        verify_fn: Callable[[], VerificationResult],
        max_retries: int = 3,
        delay: float = 1.5,
    ) -> Tuple[bool, VerificationResult]:
        """
        Execute an async action coroutine, verify its outcome, and retry on
        failure up to *max_retries* times.

        Parameters
        ----------
        action_coro:
            An *already created* coroutine that performs the automation action.
            On subsequent retries the caller is responsible for providing a
            fresh coroutine — pass a lambda/factory, not a bare call, if you
            need retries (see note below).

            .. note::
                Because a coroutine object can only be awaited once, this
                method awaits *action_coro* on the first attempt.  For retries
                it calls ``verify_fn`` again after the configured delay — it
                **does not** re-run the action unless the caller provides a
                factory.  To re-run the action on each retry, wrap this method
                in your own loop or use ``action_factory`` pattern.

        verify_fn:
            A zero-argument callable that returns a :class:`VerificationResult`.
            Called after each action attempt.

        max_retries:
            Total number of attempts (including the first).

        delay:
            Seconds to wait between attempts.

        Returns
        -------
        Tuple[bool, VerificationResult]
            ``(True, result)`` on the first successful verification,
            ``(False, last_result)`` if all attempts are exhausted.
        """
        last_result: VerificationResult = VerificationResult(
            success=False, message="Not yet attempted"
        )

        for attempt in range(1, max_retries + 1):
            logger.info(
                f"[FeedbackLoop] Attempt {attempt}/{max_retries}"
            )

            # Run the action — only the first coro object is used here
            try:
                if attempt == 1:
                    await action_coro
                else:
                    # On retry we only re-verify; caller must supply new coro
                    # for re-execution.  Sleep before re-verify.
                    await asyncio.sleep(delay)
            except Exception as exc:
                logger.error(
                    f"[FeedbackLoop] Action raised on attempt {attempt}: {exc}"
                )

            # Verify result
            try:
                last_result = verify_fn()
            except Exception as exc:
                logger.error(
                    f"[FeedbackLoop] verify_fn raised on attempt {attempt}: {exc}"
                )
                last_result = VerificationResult(
                    success=False,
                    message=f"verify_fn error: {exc}",
                )

            if last_result.success:
                logger.info(
                    f"[FeedbackLoop] ✅ Verified on attempt {attempt}"
                )
                return (True, last_result)

            logger.warning(
                f"[FeedbackLoop] Attempt {attempt} failed: {last_result.message}"
            )
            if attempt < max_retries:
                await asyncio.sleep(delay)

        logger.error(
            f"[FeedbackLoop] ❌ All {max_retries} attempts failed. "
            f"Last: {last_result.message}"
        )
        return (False, last_result)
