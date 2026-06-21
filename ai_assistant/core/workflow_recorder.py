"""
workflow_recorder.py — 'Teach Botbro' macro recording and playback system.

Allows users to record any desktop workflow (mouse clicks, keyboard input,
app opens) by demonstration, save it as a named workflow, and replay it
on demand.

Usage:
  recorder.start_recording()       # User performs actions
  recorder.stop_recording()        # Stop capturing
  recorder.save_workflow('name')   # Save to disk
  recorder.replay_workflow('name') # Replay later

Public API:
  WorkflowRecorder.start_recording()         -> str
  WorkflowRecorder.stop_recording()          -> str
  WorkflowRecorder.save_workflow(name, desc) -> str
  WorkflowRecorder.replay_workflow(name, speed) -> str
  WorkflowRecorder.list_workflows()          -> List[str]
  WorkflowRecorder.get_workflow_info(name)   -> str
  WorkflowRecorder.delete_workflow(name)     -> str
"""

import dataclasses
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Optional dependency: pynput (for recording)
# ---------------------------------------------------------------------------
try:
    from pynput import mouse as _mouse_lib, keyboard as _keyboard_lib
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False

# Optional dependency: pyautogui (for replay)
try:
    import pyautogui as _pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False

from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Directory setup — BASE_DIR is two levels up from this file
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
BASE_DIR = _THIS_FILE.parent.parent.parent  # os-controller root
WORKFLOWS_DIR = BASE_DIR / "workflows"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WorkflowEvent:
    """Represents a single captured desktop action within a recording."""
    event_type: str          # mouse_click | mouse_move | key_press | key_release | delay | app_open
    x: int = 0
    y: int = 0
    button: str = ''
    key: str = ''
    text: str = ''
    app: str = ''
    timestamp: float = 0.0
    delay_after: float = 0.0  # seconds to wait after this event during replay


@dataclass
class Workflow:
    """A complete named workflow composed of ordered desktop events."""
    name: str
    description: str
    events: List[WorkflowEvent]
    created_at: str
    replay_count: int = 0


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _safe_name(name: str) -> str:
    """Convert an arbitrary workflow name to a safe filesystem filename."""
    return re.sub(r'[^\w\-]', '_', name).strip('_').lower()


def _pixel_distance(x1: int, y1: int, x2: int, y2: int) -> float:
    """Euclidean distance between two screen coordinates."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _workflow_path(name: str) -> Path:
    """Return the JSON path for a workflow by name."""
    return WORKFLOWS_DIR / f"{_safe_name(name)}.json"


def _events_to_dicts(events: List[WorkflowEvent]) -> List[dict]:
    """Serialize a list of WorkflowEvent dataclasses to plain dicts."""
    return [dataclasses.asdict(e) for e in events]


def _events_from_dicts(raw: List[dict]) -> List[WorkflowEvent]:
    """Deserialize a list of plain dicts back into WorkflowEvent objects."""
    return [WorkflowEvent(**d) for d in raw]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class WorkflowRecorder:
    """
    Records and replays desktop macro workflows ('Teach Botbro' feature).

    Recording uses pynput to capture mouse and keyboard events in real time.
    Replay drives the desktop via pyautogui.
    Workflows are persisted as human-readable JSON files.
    """

    # Maximum gap between events preserved during replay (seconds)
    _MAX_DELAY: float = 3.0
    # Minimum pixel distance before a mouse-move event is kept
    _MIN_MOVE_PX: float = 50.0
    # Minimum time between recorded mouse-move events (seconds)
    _MOUSE_SAMPLE_RATE: float = 0.1

    def __init__(self) -> None:
        self._events: List[WorkflowEvent] = []
        self._recording: bool = False
        self._mouse_listener = None   # pynput mouse listener
        self._keyboard_listener = None  # pynput keyboard listener
        self._start_time: float = 0.0
        self._last_event_time: float = 0.0
        self._last_move_time: float = 0.0
        self._last_move_x: int = 0
        self._last_move_y: int = 0
        self._mouse_sample_rate: float = self._MOUSE_SAMPLE_RATE

        # Ensure the workflows storage directory exists
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("WorkflowRecorder initialised. Workflows dir: %s", WORKFLOWS_DIR)

    # ------------------------------------------------------------------
    # Public API — Recording
    # ------------------------------------------------------------------

    def start_recording(self) -> str:
        """
        Begin capturing mouse and keyboard events.

        Returns a status string. If pynput is unavailable, returns an
        installation hint instead of raising.
        """
        if not _PYNPUT_AVAILABLE:
            msg = "pynput not installed. Run: pip install pynput"
            logger.warning(msg)
            return msg

        if self._recording:
            return "Already recording. Call stop_recording() first."

        self._events = []
        self._recording = True
        self._start_time = time.time()
        self._last_event_time = self._start_time
        self._last_move_time = 0.0
        self._last_move_x = 0
        self._last_move_y = 0

        # Start pynput listeners (non-blocking — they run on daemon threads)
        self._mouse_listener = _mouse_lib.Listener(
            on_click=self._on_click,
            on_move=self._on_move,
        )
        self._keyboard_listener = _keyboard_lib.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

        msg = "Recording started. Perform your actions now."
        logger.info(msg)
        return msg

    def stop_recording(self) -> str:
        """
        Stop capturing events and clean up listeners.

        Filters out redundant mouse-move events (keeps only moves that are
        more than 50 px away from the previous kept move) before returning.
        """
        if not self._recording:
            return "Not currently recording."

        self._recording = False

        # Gracefully stop listeners
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception as exc:
                logger.warning("Error stopping mouse listener: %s", exc)
            self._mouse_listener = None

        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
            except Exception as exc:
                logger.warning("Error stopping keyboard listener: %s", exc)
            self._keyboard_listener = None

        # Filter noisy mouse-move events
        self._events = self._filter_mouse_moves(self._events)

        msg = f"Recording stopped. Captured {len(self._events)} events."
        logger.info(msg)
        return msg

    # ------------------------------------------------------------------
    # Public API — Persistence
    # ------------------------------------------------------------------

    def save_workflow(self, name: str, description: str = '') -> str:
        """
        Persist the current recording as a named workflow JSON file.

        Computes inter-event delays before saving so that replay timing
        is self-contained in the file.

        Args:
            name:        Human-readable workflow name.
            description: Optional description stored with the workflow.

        Returns:
            Status message string.
        """
        if not self._events:
            return "No events recorded. Use start_recording() first."

        # Stamp delays onto events before serialising
        self._compute_delays()

        workflow = Workflow(
            name=name,
            description=description,
            events=self._events,
            created_at=time.strftime("%Y-%m-%d %Human:%M:%S", time.localtime()),
            replay_count=0,
        )
        # Fix the created_at format string typo from the spec (use proper strftime)
        workflow.created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        payload = {
            "name": workflow.name,
            "description": workflow.description,
            "created_at": workflow.created_at,
            "replay_count": workflow.replay_count,
            "events": _events_to_dicts(workflow.events),
        }

        out_path = _workflow_path(name)
        try:
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save workflow '%s': %s", name, exc)
            return f"Error saving workflow: {exc}"

        msg = f'Workflow "{name}" saved with {len(self._events)} steps.'
        logger.info(msg)
        return msg

    def replay_workflow(self, name: str, speed: float = 1.0) -> str:
        """
        Load and replay a saved workflow by driving pyautogui.

        Args:
            name:  Workflow name (matches the saved JSON filename).
            speed: Playback speed multiplier. 2.0 = twice as fast.

        Returns:
            Status message string.
        """
        if not _PYAUTOGUI_AVAILABLE:
            return "pyautogui not installed. Run: pip install pyautogui"

        workflow, err = self._load_workflow(name)
        if err:
            return err

        logger.info("Replaying workflow '%s' at %.1fx speed (%d events).",
                    name, speed, len(workflow.events))

        # Disable pyautogui fail-safe during replay to avoid accidental abort
        # (re-enable afterwards)
        original_failsafe = _pyautogui.FAILSAFE
        _pyautogui.FAILSAFE = False

        import time as _time
        from core.metrics_store import get_store
        start_time = _time.perf_counter()
        success = True
        error_msg = ""

        try:
            for event in workflow.events:
                self._replay_event(event, speed)
        except Exception as exc:
            success = False
            error_msg = str(exc)
            logger.error("Error during replay of '%s': %s", name, exc)
            return f'Replay error: {exc}'
        finally:
            _pyautogui.FAILSAFE = original_failsafe
            latency_ms = (_time.perf_counter() - start_time) * 1000.0
            try:
                get_store().log_workflow(
                    workflow_name=name,
                    step_count=len(workflow.events),
                    success=success,
                    latency_ms=latency_ms,
                    error_msg=error_msg
                )
            except Exception as store_exc:
                logger.error(f"Failed to log workflow metrics: {store_exc}")

        # Increment replay counter and persist
        workflow.replay_count += 1
        self._persist_replay_count(name, workflow)

        msg = f'Workflow "{name}" replayed successfully.'
        logger.info(msg)
        return msg

    # ------------------------------------------------------------------
    # Public API — Management
    # ------------------------------------------------------------------

    def list_workflows(self) -> List[str]:
        """Return the names of all saved workflows (derived from filenames)."""
        return [p.stem for p in sorted(WORKFLOWS_DIR.glob("*.json"))]

    def get_workflow_info(self, name: str) -> str:
        """
        Return a human-readable summary of a saved workflow.

        Args:
            name: Workflow name.

        Returns:
            Multi-line summary string, or an error message.
        """
        workflow, err = self._load_workflow(name)
        if err:
            return err

        lines = [
            f"Workflow : {workflow.name}",
            f"Created  : {workflow.created_at}",
            f"Replays  : {workflow.replay_count}",
            f"Steps    : {len(workflow.events)}",
        ]
        if workflow.description:
            lines.append(f"Desc     : {workflow.description}")

        # Event type breakdown
        type_counts: dict = {}
        for ev in workflow.events:
            type_counts[ev.event_type] = type_counts.get(ev.event_type, 0) + 1
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
        lines.append(f"Breakdown: {breakdown}")

        return "\n".join(lines)

    def delete_workflow(self, name: str) -> str:
        """
        Delete a saved workflow JSON file.

        Args:
            name: Workflow name.

        Returns:
            Status message string.
        """
        path = _workflow_path(name)
        if not path.exists():
            return f'Workflow "{name}" not found.'
        try:
            path.unlink()
            msg = f'Workflow "{name}" deleted.'
            logger.info(msg)
            return msg
        except OSError as exc:
            logger.error("Failed to delete workflow '%s': %s", name, exc)
            return f"Error deleting workflow: {exc}"

    # ------------------------------------------------------------------
    # Private — pynput callbacks
    # ------------------------------------------------------------------

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        """pynput mouse click callback — records button-down events only."""
        if not self._recording or not pressed:
            return
        now = time.time()
        event = WorkflowEvent(
            event_type="mouse_click",
            x=int(x),
            y=int(y),
            button=str(button),
            timestamp=now,
        )
        self._events.append(event)
        self._last_event_time = now
        logger.debug("Recorded mouse_click at (%d, %d) button=%s", x, y, button)

    def _on_move(self, x: int, y: int) -> None:
        """
        pynput mouse move callback.

        Records a move event only if:
          - At least _MOUSE_SAMPLE_RATE seconds have passed since last recorded move, AND
          - The cursor has moved at least 50 px from the last recorded move position.
        """
        if not self._recording:
            return
        now = time.time()
        elapsed = now - self._last_move_time
        distance = _pixel_distance(self._last_move_x, self._last_move_y, x, y)

        if elapsed < self._mouse_sample_rate or distance < self._MIN_MOVE_PX:
            return

        event = WorkflowEvent(
            event_type="mouse_move",
            x=int(x),
            y=int(y),
            timestamp=now,
        )
        self._events.append(event)
        self._last_move_time = now
        self._last_move_x = int(x)
        self._last_move_y = int(y)
        self._last_event_time = now
        logger.debug("Recorded mouse_move to (%d, %d)", x, y)

    def _on_key_press(self, key) -> None:
        """pynput keyboard press callback."""
        if not self._recording:
            return
        now = time.time()
        event = WorkflowEvent(
            event_type="key_press",
            key=str(key),
            timestamp=now,
        )
        self._events.append(event)
        self._last_event_time = now
        logger.debug("Recorded key_press: %s", key)

    def _on_key_release(self, key) -> None:
        """pynput keyboard release callback."""
        if not self._recording:
            return
        now = time.time()
        event = WorkflowEvent(
            event_type="key_release",
            key=str(key),
            timestamp=now,
        )
        self._events.append(event)
        self._last_event_time = now
        logger.debug("Recorded key_release: %s", key)

    # ------------------------------------------------------------------
    # Private — pre-save processing
    # ------------------------------------------------------------------

    def _compute_delays(self) -> None:
        """
        Compute the ``delay_after`` field for each event.

        The delay is the wall-clock gap to the *next* event, capped at
        ``_MAX_DELAY`` seconds to avoid excessively long replays when the
        user paused during recording.
        """
        for i, event in enumerate(self._events):
            if i < len(self._events) - 1:
                gap = self._events[i + 1].timestamp - event.timestamp
                event.delay_after = min(max(gap, 0.0), self._MAX_DELAY)
            else:
                event.delay_after = 0.0  # last event — no trailing delay

    @staticmethod
    def _filter_mouse_moves(events: List[WorkflowEvent]) -> List[WorkflowEvent]:
        """
        Remove redundant mouse_move events from a captured sequence.

        Keeps a mouse_move only if it is more than 50 px from the
        previously kept mouse_move.  All other event types are kept
        unconditionally.
        """
        filtered: List[WorkflowEvent] = []
        last_kept_x: int = -1
        last_kept_y: int = -1

        for event in events:
            if event.event_type != "mouse_move":
                filtered.append(event)
                continue

            if last_kept_x == -1:
                # First move — always keep
                filtered.append(event)
                last_kept_x, last_kept_y = event.x, event.y
                continue

            dist = _pixel_distance(last_kept_x, last_kept_y, event.x, event.y)
            if dist >= 50.0:
                filtered.append(event)
                last_kept_x, last_kept_y = event.x, event.y

        return filtered

    # ------------------------------------------------------------------
    # Private — replay helpers
    # ------------------------------------------------------------------

    def _replay_event(self, event: WorkflowEvent, speed: float) -> None:
        """Execute a single WorkflowEvent using pyautogui."""
        etype = event.event_type

        if etype == "mouse_click":
            # Map pynput button string → pyautogui button name
            btn = self._map_button(event.button)
            logger.debug("Replay click at (%d, %d) btn=%s", event.x, event.y, btn)
            _pyautogui.click(event.x, event.y, button=btn)

        elif etype == "mouse_move":
            logger.debug("Replay move to (%d, %d)", event.x, event.y)
            _pyautogui.moveTo(event.x, event.y)

        elif etype == "key_press":
            key_name = self._normalise_key(event.key)
            logger.debug("Replay keyDown: %s", key_name)
            try:
                _pyautogui.keyDown(key_name)
            except Exception as exc:
                logger.warning("keyDown(%s) failed: %s", key_name, exc)

        elif etype == "key_release":
            key_name = self._normalise_key(event.key)
            logger.debug("Replay keyUp: %s", key_name)
            try:
                _pyautogui.keyUp(key_name)
            except Exception as exc:
                logger.warning("keyUp(%s) failed: %s", key_name, exc)

        elif etype == "delay":
            time.sleep(event.delay_after / max(speed, 0.01))
            return  # skip the trailing delay below for delay events

        elif etype == "app_open":
            # App-open events are intentionally skipped during replay.
            # The assumption is that required apps are already open.
            logger.debug("Skipping app_open event for '%s' during replay.", event.app)

        # Apply the inter-event delay (speed-adjusted)
        if event.delay_after > 0:
            time.sleep(event.delay_after / max(speed, 0.01))

    @staticmethod
    def _map_button(pynput_button: str) -> str:
        """
        Convert a pynput Button string to a pyautogui button name.

        Examples:
          'Button.left'  -> 'left'
          'Button.right' -> 'right'
          'Button.middle'-> 'middle'
        """
        lower = pynput_button.lower()
        if "right" in lower:
            return "right"
        if "middle" in lower:
            return "middle"
        return "left"

    @staticmethod
    def _normalise_key(pynput_key: str) -> str:
        """
        Convert a pynput key string to a pyautogui-compatible key name.

        pynput represents special keys as e.g. ``Key.ctrl_l``, ``Key.enter``.
        pyautogui uses ``'ctrl'``, ``'enter'``, etc.

        Regular characters are stored as ``'a'`` (with quotes) by pynput,
        so we strip the surrounding quotes.
        """
        # Remove surrounding single quotes (regular chars: "'a'" -> "a")
        key = pynput_key.strip("'")

        # Map pynput Key.xxx -> pyautogui name
        _KEY_MAP = {
            "Key.enter":       "enter",
            "Key.space":       "space",
            "Key.tab":         "tab",
            "Key.backspace":   "backspace",
            "Key.delete":      "delete",
            "Key.escape":      "escape",
            "Key.shift":       "shift",
            "Key.shift_l":     "shiftleft",
            "Key.shift_r":     "shiftright",
            "Key.ctrl":        "ctrl",
            "Key.ctrl_l":      "ctrlleft",
            "Key.ctrl_r":      "ctrlright",
            "Key.alt":         "alt",
            "Key.alt_l":       "altleft",
            "Key.alt_r":       "altright",
            "Key.cmd":         "win",
            "Key.cmd_l":       "winleft",
            "Key.cmd_r":       "winright",
            "Key.caps_lock":   "capslock",
            "Key.home":        "home",
            "Key.end":         "end",
            "Key.page_up":     "pageup",
            "Key.page_down":   "pagedown",
            "Key.up":          "up",
            "Key.down":        "down",
            "Key.left":        "left",
            "Key.right":       "right",
            "Key.f1":  "f1",  "Key.f2":  "f2",  "Key.f3":  "f3",
            "Key.f4":  "f4",  "Key.f5":  "f5",  "Key.f6":  "f6",
            "Key.f7":  "f7",  "Key.f8":  "f8",  "Key.f9":  "f9",
            "Key.f10": "f10", "Key.f11": "f11", "Key.f12": "f12",
        }

        return _KEY_MAP.get(key, key)

    # ------------------------------------------------------------------
    # Private — JSON I/O
    # ------------------------------------------------------------------

    def _load_workflow(self, name: str):
        """
        Load a workflow from disk.

        Returns:
            (Workflow, None) on success.
            (None, error_str) on failure.
        """
        path = _workflow_path(name)
        if not path.exists():
            return None, f'Workflow "{name}" not found. Available: {self.list_workflows()}'
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            workflow = Workflow(
                name=raw["name"],
                description=raw.get("description", ""),
                events=_events_from_dicts(raw.get("events", [])),
                created_at=raw.get("created_at", ""),
                replay_count=raw.get("replay_count", 0),
            )
            return workflow, None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("Corrupt workflow file '%s': %s", path, exc)
            return None, f"Failed to load workflow '{name}': {exc}"

    def _persist_replay_count(self, name: str, workflow: Workflow) -> None:
        """Silently update the replay_count in the stored JSON."""
        path = _workflow_path(name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["replay_count"] = workflow.replay_count
            path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not update replay_count for '%s': %s", name, exc)
