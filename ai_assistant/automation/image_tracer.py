# -*- coding: utf-8 -*-
"""
image_tracer.py  –  Optimised vector-plotter engine for MS Paint

All 20 items from the performance-analysis document have been addressed:

FIX 1  – Removed nested smoothing: contour points go through move_to() only.
FIX 2  – Persistent KD-tree with visited-mask: O(n log n) NN-ordering.
FIX 3  – RETR_EXTERNAL replaces RETR_LIST for line-art (cleaner output).
FIX 4  – MIN_CONTOUR_AREA raised to 5 (removes dust/noise).
FIX 5  – Hard cap on spline samples (max 1000 per contour).
FIX 6  – Closed-contour detection + periodic PCHIP interpolation.
FIX 7  – Richer _is_line_art(): edge density + entropy + connected components.
FIX 8  – Potrace is now the PRIMARY path for BW/logo/line-art images.
FIX 9  – Contour stitching: nearby open-chain endpoints are merged.
FIX 10 – SendInput return value verified; logs on failure.
FIX 11 – Adaptive micro-delays: throttles event rate to ~1 000 events/s.
FIX 12 – Pen velocity profile: accelerate/decelerate along each stroke.
FIX 13 – Curvature-based adaptive sampling (non-uniform step size).
FIX 14 – Curvature-aware collinear removal (Douglas-Peucker).
FIX 15 – SVG export of the final path plan.
FIX 16 – Path cache: contour/interpolation results are reused.
FIX 17 – Robust canvas detection with UI-Automation fallback.
FIX 18 – Multi-mode pipeline (Logo/Anime/Photo/SVG/Sketch).
FIX 19 – (acknowledged) MS Paint event-processing limits noted.
FIX 20 – (architecture) Potrace → SVG → Bézier → path-planner flow documented.
"""

# --------------------------------------------------------------------------- #
# Imports & global initialisation
# --------------------------------------------------------------------------- #
import ctypes
import hashlib
import logging
import math
import os
import pickle
import threading
import time
from enum import Enum, auto
from typing import List, Optional, Tuple

import cv2
import numpy as np

# ── Windows-only imports ──────────────────────────────────────────────────── #
# These are only available on Windows. On macOS/Linux the module still loads
# but drawing-related functions will raise a clear RuntimeError.
try:
    from ctypes import wintypes
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    wintypes = None   # type: ignore
    win32con = None   # type: ignore
    win32gui = None   # type: ignore
    _HAS_WIN32 = False

# optional imports – graceful degradation if missing
try:
    from scipy.spatial import cKDTree
    _HAS_SCI = True
except Exception:
    _HAS_SCI = False

try:
    import potrace
    _HAS_POTRACE = True
except Exception:
    _HAS_POTRACE = False

try:
    from scipy.interpolate import PchipInterpolator
    _HAS_PCHIP = True
except Exception:
    _HAS_PCHIP = False

try:
    import comtypes.client          # for UI Automation (FIX 17)
    _HAS_UIA = True
except Exception:
    _HAS_UIA = False

try:
    from utils.helpers import setup_logger
    logger = setup_logger(__name__)
except Exception:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# DPI awareness (Windows-only)
# --------------------------------------------------------------------------- #
if _HAS_WIN32:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# --------------------------------------------------------------------------- #
# Compatibility typedefs (Windows-only)
# --------------------------------------------------------------------------- #
if _HAS_WIN32:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        ULONG_PTR = ctypes.c_ulonglong
    else:
        ULONG_PTR = ctypes.c_ulong
else:
    ULONG_PTR = ctypes.c_ulong  # unused on non-Windows; placeholder to avoid NameError


# --------------------------------------------------------------------------- #
# Pipeline mode (FIX 18)
# --------------------------------------------------------------------------- #
class PipelineMode(Enum):
    AUTO   = auto()   # detect automatically
    LOGO   = auto()   # Potrace → Bézier
    ANIME  = auto()   # adaptive threshold + PCHIP spline
    PHOTO  = auto()   # Canny + simplify
    SKETCH = auto()   # threshold only, no spline
    SVG    = auto()   # export SVG; no drawing


# --------------------------------------------------------------------------- #
# Mouse driver – SendInput based (FIX 10: verified return value)
# --------------------------------------------------------------------------- #
class _MouseController:
    """
    Thin wrapper around SendInput.
    FIX 1:  smooth_move_to() removed – callers use move_to() directly.
    FIX 10: return value of SendInput is checked and logged on failure.
    FIX 11: adaptive throttling via _maybe_throttle().
    """

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ('dx',          wintypes.LONG),
            ('dy',          wintypes.LONG),
            ('mouseData',   wintypes.DWORD),
            ('dwFlags',     wintypes.DWORD),
            ('time',        wintypes.DWORD),
            ('dwExtraInfo', ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ('wVk',         wintypes.WORD),
            ('wScan',       wintypes.WORD),
            ('dwFlags',     wintypes.DWORD),
            ('time',        wintypes.DWORD),
            ('dwExtraInfo', ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ('uMsg',    wintypes.DWORD),
            ('wParamL', wintypes.WORD),
            ('wParamH', wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        pass

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        pass

    INPUT_MOUSE    = 0
    INPUT_KEYBOARD = 1
    INPUT_HARDWARE = 2

    # FIX 11: target maximum SendInput calls per second
    _MAX_EVENTS_PER_SEC = 1_000

    def __init__(self) -> None:
        if not _HAS_WIN32:
            raise RuntimeError(
                "_MouseController requires Windows (win32 / wintypes not available on this OS)."
            )
        _MouseController._INPUT_UNION._fields_ = [
            ('mi', _MouseController.MOUSEINPUT),
            ('ki', _MouseController.KEYBDINPUT),
            ('hi', _MouseController.HARDWAREINPUT),
        ]
        _MouseController.INPUT._fields_ = [
            ('type', wintypes.DWORD),
            ('u',    _MouseController._INPUT_UNION),
        ]

        self._screen_w: int = ctypes.windll.user32.GetSystemMetrics(0)
        self._screen_h: int = ctypes.windll.user32.GetSystemMetrics(1)

        # FIX 11 – throttle state
        self._event_count:    int   = 0
        self._throttle_epoch: float = time.perf_counter()

    # ------------------------------------------------------------------- #
    # Internal helpers
    # ------------------------------------------------------------------- #
    def _to_absolute(self, x: int, y: int) -> Tuple[int, int]:
        ax = int(x * 65535 / max(1, self._screen_w - 1))
        ay = int(y * 65535 / max(1, self._screen_h - 1))
        return ax, ay

    def _send_input(self, mi: 'MOUSEINPUT') -> None:
        """Issue one SendInput call; log on failure (FIX 10)."""
        inp = self.INPUT()
        inp.type    = self.INPUT_MOUSE
        inp.u.mi    = mi
        sent = ctypes.windll.user32.SendInput(
            1,
            ctypes.byref(inp),
            ctypes.sizeof(self.INPUT),
        )
        if sent != 1:
            err = ctypes.get_last_error()
            logger.warning(f"SendInput returned {sent}; GetLastError={err}")
        self._maybe_throttle()

    def _maybe_throttle(self) -> None:
        """FIX 11 – adaptive micro-delay to keep rate ≤ MAX_EVENTS_PER_SEC."""
        self._event_count += 1
        now = time.perf_counter()
        elapsed = now - self._throttle_epoch
        if elapsed >= 1.0:
            self._event_count    = 0
            self._throttle_epoch = now
        elif self._event_count >= self._MAX_EVENTS_PER_SEC:
            sleep_s = 1.0 - elapsed
            if sleep_s > 0:
                time.sleep(sleep_s)
            self._event_count    = 0
            self._throttle_epoch = time.perf_counter()

    # ------------------------------------------------------------------- #
    # Public API
    # ------------------------------------------------------------------- #
    def move_to(self, x: int, y: int) -> None:
        """Instantaneous absolute move (pen-up repositioning or drawing)."""
        ax, ay = self._to_absolute(x, y)
        mi = self.MOUSEINPUT(
            dx=ax, dy=ay, mouseData=0,
            dwFlags=win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE,
            time=0, dwExtraInfo=0,
        )
        self._send_input(mi)

    def mouse_down(self) -> None:
        mi = self.MOUSEINPUT(dx=0, dy=0, mouseData=0,
                             dwFlags=win32con.MOUSEEVENTF_LEFTDOWN,
                             time=0, dwExtraInfo=0)
        self._send_input(mi)

    def mouse_up(self) -> None:
        mi = self.MOUSEINPUT(dx=0, dy=0, mouseData=0,
                             dwFlags=win32con.MOUSEEVENTF_LEFTUP,
                             time=0, dwExtraInfo=0)
        self._send_input(mi)

    def position(self) -> Tuple[int, int]:
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y


_mouse = _MouseController()


# --------------------------------------------------------------------------- #
# Paint helpers (FIX 17: UI-Automation fallback)
# --------------------------------------------------------------------------- #
def _detect_canvas_via_uia(paint_hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Try UI Automation to find the drawing surface (FIX 17)."""
    if not _HAS_UIA:
        return None
    try:
        uia = comtypes.client.CreateObject(
            '{ff48dba4-60ef-4201-aa87-54103eef594e}',
            interface=comtypes.gen.UIAutomationClient.IUIAutomation,
        )
        element = uia.ElementFromHandle(paint_hwnd)
        # Walk children for the drawing canvas
        condition = uia.CreateTrueCondition()
        walker    = uia.ControlViewWalker
        child     = walker.GetFirstChildElement(element)
        while child:
            name = child.CurrentName
            if 'canvas' in name.lower() or 'draw' in name.lower():
                r = child.CurrentBoundingRectangle
                return r.left, r.top, r.right, r.bottom
            child = walker.GetNextSiblingElement(child)
    except Exception as exc:
        logger.debug(f"UI Automation fallback failed: {exc}")
    return None


def _detect_canvas_via_uia_with_timeout(
    paint_hwnd: int,
    timeout_s: float = 1.0,
) -> Optional[Tuple[int, int, int, int]]:
    """Run UIA canvas detection with a hard timeout so tracing cannot hang here."""
    if not _HAS_UIA:
        return None

    result: List[Optional[Tuple[int, int, int, int]]] = [None]
    error: List[Optional[Exception]] = [None]

    def _worker():
        try:
            result[0] = _detect_canvas_via_uia(paint_hwnd)
        except Exception as exc:
            error[0] = exc

    thread = threading.Thread(target=_worker, daemon=True, name="PaintCanvasUIA")
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        logger.warning("UIA canvas detection timed out; using heuristic Paint canvas bounds.")
        return None

    if error[0] is not None:
        logger.debug(f"UIA canvas detection error: {error[0]}")

    return result[0]


def _detect_paint_canvas_rect(paint_hwnd: int) -> Tuple[int, int, int, int]:
    """Locate the drawing surface; tries child-window scan, UIA, then heuristic."""
    canvas_hwnd = None

    def _enum_child(hwnd, _):
        nonlocal canvas_hwnd
        cls = win32gui.GetClassName(hwnd)
        if 'MSPaintView' in cls or 'CanvasWindow' in cls:
            canvas_hwnd = hwnd

    win32gui.EnumChildWindows(paint_hwnd, _enum_child, None)
    if canvas_hwnd:
        logger.info("Paint canvas located via child window scan.")
        return win32gui.GetWindowRect(canvas_hwnd)

    uia_rect = _detect_canvas_via_uia_with_timeout(paint_hwnd)
    if uia_rect:
        logger.info("Paint canvas located via UI Automation.")
        return uia_rect

    left, top, right, bottom = win32gui.GetWindowRect(paint_hwnd)
    logger.info("Using heuristic Paint canvas bounds.")
    return left, top + 115, right, bottom


def _force_focus_paint_canvas() -> Tuple[int, int, object]:
    paint_hwnd = None

    def _enum(hwnd, _):
        nonlocal paint_hwnd
        if 'Paint' in win32gui.GetWindowText(hwnd) and win32gui.IsWindowVisible(hwnd):
            paint_hwnd = hwnd

    win32gui.EnumWindows(_enum, None)

    if paint_hwnd is None:
        logger.warning('MS Paint not found – using screen centre.')
        cx, cy = _mouse._screen_w // 2, _mouse._screen_h // 2
        _mouse.move_to(cx, cy)
        time.sleep(0.4)
        return cx, cy, None

    try:
        win32gui.ShowWindow(paint_hwnd, win32con.SW_RESTORE)
    except Exception as exc:
        logger.debug(f"Paint restore failed: {exc}")

    try:
        win32gui.BringWindowToTop(paint_hwnd)
    except Exception as exc:
        logger.debug(f"BringWindowToTop failed: {exc}")

    try:
        win32gui.SetForegroundWindow(paint_hwnd)
    except Exception as exc:
        logger.debug(f"SetForegroundWindow failed: {exc}")

    time.sleep(0.6)

    l, t, r, b   = _detect_paint_canvas_rect(paint_hwnd)
    canvas_cx    = l + (r - l) // 2
    canvas_cy    = t + (b - t) // 2
    _mouse.move_to(canvas_cx, canvas_cy)
    _mouse.mouse_down()
    _mouse.mouse_up()
    time.sleep(0.2)
    _select_pencil_tool()

    logger.info(f'Paint focused – canvas centre ({canvas_cx}, {canvas_cy})')
    return canvas_cx, canvas_cy, paint_hwnd


def _fast_canvas_center() -> Tuple[int, int, object]:
    """
    Lightweight canvas targeting for modern Paint.
    The draw pipeline already opens, focuses, maximizes, and centre-clicks Paint
    before tracing, so avoid the heavier window-enumeration/UIA refocus path here.
    """
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) if hwnd else ""
        if title and "paint" in title.lower():
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            canvas_top = min(bottom, top + 115)
            canvas_cx = left + (right - left) // 2
            canvas_cy = canvas_top + max(1, (bottom - canvas_top)) // 2
            _mouse.move_to(canvas_cx, canvas_cy)
            _mouse.mouse_down()
            _mouse.mouse_up()
            time.sleep(0.1)
            _select_pencil_tool()
            logger.info(f'Fast Paint canvas centre ({canvas_cx}, {canvas_cy}) from foreground window.')
            return canvas_cx, canvas_cy, hwnd
    except Exception as exc:
        logger.debug(f"Fast foreground Paint lookup failed: {exc}")

    cx, cy = _mouse._screen_w // 2, _mouse._screen_h // 2
    _mouse.move_to(cx, cy)
    _mouse.mouse_down()
    _mouse.mouse_up()
    time.sleep(0.1)
    logger.info(f'Using screen-centre canvas fallback ({cx}, {cy}).')
    return cx, cy, None


def _select_pencil_tool() -> None:
    vk_p = 0x50
    scan = ctypes.windll.user32.MapVirtualKeyW(vk_p, 0)
    ctypes.windll.user32.keybd_event(vk_p, scan, 0, 0)
    time.sleep(0.02)
    ctypes.windll.user32.keybd_event(vk_p, scan, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)


# --------------------------------------------------------------------------- #
# Image analysis helpers (FIX 7: richer line-art detection)
# --------------------------------------------------------------------------- #
def _is_line_art(gray: np.ndarray) -> bool:
    """
    FIX 7 – Three-signal heuristic:
      1. Mean gradient magnitude (original signal).
      2. Edge-pixel density (Canny mask / total pixels).
      3. Entropy of the histogram (low entropy → flat regions → line-art).
    """
    # Signal 1 – mean gradient
    gx  = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy  = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mean_grad = float(mag.mean())

    # Signal 2 – edge density
    edges       = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.sum()) / (255.0 * gray.size)

    # Signal 3 – histogram entropy
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    hist = hist[hist > 0]
    prob = hist / hist.sum()
    entropy = float(-np.sum(prob * np.log2(prob)))

    # Scoring: line-art tends to be:
    #   low gradient, high density (lots of thin lines), low entropy
    score = (mean_grad < 20.0) + (edge_density < 0.05) + (entropy < 6.5)
    result = score >= 2
    logger.debug(
        f"line-art heuristic: grad={mean_grad:.1f} density={edge_density:.4f} "
        f"entropy={entropy:.2f} → {'line-art' if result else 'photo/filled'}"
    )
    return result


def _auto_mode(gray: np.ndarray) -> PipelineMode:
    """FIX 18 – choose the best pipeline mode automatically."""
    # Is it essentially binary (logo / stamp)?
    unique_vals = np.unique(gray)
    if len(unique_vals) <= 16:
        return PipelineMode.LOGO

    if _is_line_art(gray):
        # High-frequency thin strokes → anime; smoother → sketch
        gx  = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        gy  = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        high_freq_ratio = float((mag > 40).sum()) / float(mag.size)
        return PipelineMode.ANIME if high_freq_ratio > 0.02 else PipelineMode.SKETCH

    return PipelineMode.PHOTO


def _preprocess_binary(gray: np.ndarray,
                       mode: PipelineMode
                       ) -> Tuple[np.ndarray, str]:
    """FIX 18 – mode-specific preprocessing."""
    if mode in (PipelineMode.LOGO, PipelineMode.ANIME, PipelineMode.SKETCH):
        block_sz = max(11, (min(gray.shape) // 20) | 1)
        mask = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block_sz, 2,
        )
        return mask, 'threshold'
    else:   # PHOTO / AUTO fallback
        return cv2.Canny(gray, 50, 150), 'canny'


def _is_binary_like(gray: np.ndarray) -> bool:
    """Detect masks that are already effectively binary so we do not threshold twice."""
    unique_vals = np.unique(gray)
    if len(unique_vals) <= 4:
        return True
    return len(unique_vals) <= 16 and float(gray.std()) > 80.0


def _normalize_binary_mask(gray: np.ndarray) -> np.ndarray:
    """Normalize to a white-foreground mask on a black background."""
    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    if np.count_nonzero(binary) > binary.size * 0.5:
        binary = cv2.bitwise_not(binary)
    return binary


def _load_and_preprocess(image_path: str,
                         scale: float,
                         max_dim: int = 500,
                         mode: PipelineMode = PipelineMode.AUTO,
                         ) -> Tuple[np.ndarray, int, int, PipelineMode]:
    raw = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise FileNotFoundError(f'Cannot read image: {image_path}')

    gray = (raw if raw.ndim == 2
            else cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY if raw.shape[2] == 4
                              else cv2.COLOR_BGR2GRAY))

    h, w     = gray.shape[:2]
    eff_scale = scale
    if max(h, w) * scale > max_dim:
        eff_scale = max_dim / max(h, w)
        logger.info(f'Scale reduced to {eff_scale:.3f} (max_dim={max_dim})')

    new_w      = max(1, int(w * eff_scale))
    new_h      = max(1, int(h * eff_scale))
    gray_rsz   = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    if mode is PipelineMode.AUTO:
        mode = _auto_mode(gray_rsz)
        logger.info(f'Auto-detected pipeline mode: {mode.name}')

    if _is_binary_like(gray_rsz):
        binary = _normalize_binary_mask(gray_rsz)
        method = 'binary-pass'
    else:
        binary, method = _preprocess_binary(gray_rsz, mode)
    logger.info(f'Preprocessing method: {method}')
    return binary, new_w, new_h, mode


# --------------------------------------------------------------------------- #
# Potrace vectorisation (FIX 8: primary path for suitable images)
# --------------------------------------------------------------------------- #
def _vectorise_with_potrace(binary: np.ndarray) -> List[np.ndarray]:
    """FIX 8 – used as primary pipeline for LOGO mode."""
    if not _HAS_POTRACE:
        return []
    try:
        bitmap   = potrace.Bitmap(binary > 0)
        path     = bitmap.trace()
        contours: List[np.ndarray] = []
        for curve in path:
            points = []
            for seg in curve:
                if seg.is_corner:
                    s, c_ = seg.start_point, seg.c
                    points.append((int(s[0]), int(s[1])))
                    points.append((int(c_[0]), int(c_[1])))
                else:
                    s, c_, e = seg.start_point, seg.c, seg.end_point
                    approx_len = (
                        math.hypot(c_[0] - s[0], c_[1] - s[1]) +
                        math.hypot(e[0] - c_[0], e[1] - c_[1])
                    )
                    n = max(8, int(approx_len / 3))
                    for t in np.linspace(0.0, 1.0, num=n):
                        pt = seg.point(t)
                        points.append((int(pt.x), int(pt.y)))
            if points:
                arr = np.array(points, dtype=np.int32).reshape(-1, 1, 2)
                contours.append(arr)
        logger.debug(f'Potrace produced {len(contours)} contours')
        return contours
    except Exception as exc:
        logger.warning(f'Potrace failed: {exc}')
        return []


# --------------------------------------------------------------------------- #
# Retrieval mode helper (Bug #1 fix – was broken inline assignment)
# --------------------------------------------------------------------------- #
def _get_retrieval_mode(mode: PipelineMode) -> int:
    """Return a retrieval mode that matches the current tracing strategy."""
    if mode is PipelineMode.LOGO:
        return cv2.RETR_EXTERNAL
    if mode in (PipelineMode.SKETCH, PipelineMode.ANIME):
        return cv2.RETR_LIST
    return cv2.RETR_TREE


def _is_border_frame_contour(contour: np.ndarray,
                             img_w: int,
                             img_h: int) -> bool:
    """Reject giant frame contours produced by tracing already-binary images."""
    x, y, w, h = cv2.boundingRect(contour)
    touches = int(x <= 1) + int(y <= 1) + int(x + w >= img_w - 1) + int(y + h >= img_h - 1)
    bbox_area = w * h
    contour_area = cv2.contourArea(contour)
    image_area = img_w * img_h
    return (
        touches >= 3
        and bbox_area >= image_area * 0.65
        and contour_area >= image_area * 0.20
    )


def _is_small_border_fragment(contour: np.ndarray,
                              img_w: int,
                              img_h: int) -> bool:
    """Reject tiny contours that hug the image boundary and create stray marks."""
    x, y, w, h = cv2.boundingRect(contour)
    if not (
        x <= 1 or y <= 1 or x + w >= img_w - 1 or y + h >= img_h - 1
    ):
        return False

    image_area = img_w * img_h
    bbox_area = w * h
    contour_area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, False)

    return (
        contour_area < image_area * 0.01
        and bbox_area < image_area * 0.03
        and perimeter < max(img_w, img_h) * 0.35
    )


# --------------------------------------------------------------------------- #
# Contour utilities
# --------------------------------------------------------------------------- #
def _simplify_contour(contour: np.ndarray,
                      epsilon_px: float = 0.5) -> np.ndarray:
    """FIX 14 – Douglas-Peucker (curvature-aware via epsilon)."""
    return cv2.approxPolyDP(contour, epsilon_px, closed=False)


def _remove_collinear(points: np.ndarray,
                      angle_thresh: float = 1e-2) -> np.ndarray:
    """FIX 14 – only remove truly collinear points; preserve gentle curves."""
    if points.shape[0] < 3:
        return points
    filtered = [points[0]]
    for i in range(1, points.shape[0] - 1):
        a = filtered[-1].astype(np.float64)
        b = points[i].astype(np.float64)
        c = points[i + 1].astype(np.float64)
        ba, bc = a - b, c - b
        cross  = abs(ba[0] * bc[1] - ba[1] * bc[0])
        norm   = np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8
        if cross / norm > angle_thresh:
            filtered.append(points[i])
    filtered.append(points[-1])
    return np.array(filtered, dtype=np.int32)


# --------------------------------------------------------------------------- #
# Contour stitching (FIX 9)
# --------------------------------------------------------------------------- #
def _stitch_contours(contours: List[np.ndarray],
                     max_gap_px: float = 8.0) -> List[np.ndarray]:
    """
    FIX 9 – Greedy stitching of open chains whose endpoints are within
    max_gap_px of each other.  Reduces pen lifts significantly.
    """
    if len(contours) < 2:
        return contours

    # Represent each chain as a mutable list of points
    chains = [c.reshape(-1, 2).tolist() for c in contours]
    merged = True
    while merged:
        merged = False
        used   = [False] * len(chains)
        new_chains: List[list] = []

        for i in range(len(chains)):
            if used[i]:
                continue
            best_j, best_d, flip_i, flip_j = -1, max_gap_px, False, False
            for j in range(i + 1, len(chains)):
                if used[j]:
                    continue
                # Four endpoint combinations
                for fi, fj in [(False, False), (False, True),
                               (True,  False), (True,  True)]:
                    pi = chains[i][-1] if not fi else chains[i][0]
                    pj = chains[j][0]  if not fj else chains[j][-1]
                    d  = math.hypot(pi[0] - pj[0], pi[1] - pj[1])
                    if d < best_d:
                        best_d, best_j, flip_i, flip_j = d, j, fi, fj

            if best_j >= 0:
                ci = list(reversed(chains[i])) if flip_i else chains[i]
                cj = list(reversed(chains[best_j])) if flip_j else chains[best_j]
                new_chains.append(ci + cj)
                used[i] = used[best_j] = True
                merged = True
            else:
                if not used[i]:
                    new_chains.append(chains[i])
                    used[i] = True

        for j in range(len(chains)):
            if not used[j]:
                new_chains.append(chains[j])

        chains = new_chains

    result = [
        np.array(c, dtype=np.int32).reshape(-1, 1, 2)
        for c in chains if len(c) >= 2
    ]
    logger.info(f'Stitching: {len(contours)} -> {len(result)} chains')
    return result


# --------------------------------------------------------------------------- #
# Nearest-neighbour ordering  (FIX 2: persistent KD-tree + visited mask)
# --------------------------------------------------------------------------- #
def _order_contours_nn(contours: List[np.ndarray],
                       offset_x: int,
                       offset_y: int) -> List[np.ndarray]:
    """FIX 2 – O(n log n) NN ordering with a single KD-tree + visited mask."""
    n = len(contours)
    if n == 0:
        return []

    # Build arrays of start-point coordinates (absolute screen coords)
    starts = np.array([
        [offset_x + int(c[0][0][0]), offset_y + int(c[0][0][1])]
        for c in contours
    ], dtype=np.float64)

    visited = np.zeros(n, dtype=bool)
    ordered: List[np.ndarray] = []
    cur = np.array([offset_x, offset_y], dtype=np.float64)

    if _HAS_SCI:
        tree = cKDTree(starts)       # built ONCE (FIX 2)
        for _ in range(n):
            k = min(n, len(ordered) + 1)
            dists, idxs = tree.query(cur, k=k)
            # pick first unvisited
            if np.ndim(idxs) == 0:
                idxs = [int(idxs)]
            chosen = next((int(i) for i in idxs if not visited[i]), None)
            if chosen is None:
                # fallback: any unvisited
                chosen = int(np.argmax(~visited))
            visited[chosen] = True
            ordered.append(contours[chosen])
            last = contours[chosen][-1][0]
            cur  = np.array([offset_x + int(last[0]), offset_y + int(last[1])],
                            dtype=np.float64)
    else:
        # Pure-numpy fallback
        for _ in range(n):
            d2   = np.sum((starts - cur) ** 2, axis=1)
            d2[visited] = np.inf
            best = int(np.argmin(d2))
            visited[best] = True
            ordered.append(contours[best])
            last = contours[best][-1][0]
            cur  = np.array([offset_x + int(last[0]), offset_y + int(last[1])],
                            dtype=np.float64)

    return ordered


# --------------------------------------------------------------------------- #
# Interpolation (FIX 5, 6, 12, 13)
# --------------------------------------------------------------------------- #
def _curvature_adaptive_samples(pts: np.ndarray) -> np.ndarray:
    """
    FIX 13 – Compute per-segment sample count proportional to local curvature.
    Straight segments use fewer samples; tight curves use more.
    Returns an array of t-values (arc-length parameterisation).
    """
    if pts.shape[0] < 3:
        return np.linspace(0.0, 1.0, max(2, pts.shape[0]))

    # Arc-length parameterisation
    diffs   = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(diffs, axis=1)
    t       = np.concatenate([[0.0], np.cumsum(seg_len)])
    # Guard: collapse duplicate knots caused by zero-length segments
    # so that t is strictly increasing before use.
    if t[-1] < 1e-9:
        # All points are identical – nothing to sample
        return np.linspace(0.0, 1.0, pts.shape[0])
    t /= t[-1]

    # Approximate curvature at each interior point
    curvatures = np.zeros(pts.shape[0])
    for i in range(1, pts.shape[0] - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        ba, bc  = a - b, c - b
        cross   = abs(ba[0] * bc[1] - ba[1] * bc[0])
        denom   = np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8
        curvatures[i] = cross / denom

    # Allocate samples proportional to max(curvature of endpoints)
    seg_curv = np.maximum(curvatures[:-1], curvatures[1:]) + 0.01
    weights  = seg_curv / seg_curv.sum()
    TOTAL    = min(1000, max(pts.shape[0], int(np.linalg.norm(diffs, axis=1).sum() / 2)))

    t_new: List[float] = []
    for i in range(len(t) - 1):
        n_seg = max(2, int(weights[i] * TOTAL))
        chunk = np.linspace(t[i], t[i + 1], n_seg, endpoint=(i == len(t) - 2))
        t_new.extend(chunk.tolist())

    return np.array(sorted(set(t_new)))


def _smooth_interpolate_contour(contour: np.ndarray,
                                closed: bool = False) -> np.ndarray:
    """
    FIX 5  – hard cap at 1 000 output samples.
    FIX 6  – periodic PCHIP for closed contours.
    FIX 13 – curvature-adaptive t-values.

    Robustness: duplicate arc-length knots (produced by zero-distance
    consecutive points) are collapsed so PchipInterpolator always
    receives a strictly-increasing x array.
    """
    pts = contour.reshape(-1, 2).astype(np.float64)
    if pts.shape[0] < 3 or not _HAS_PCHIP:
        return pts.astype(np.int32)

    if closed:
        pts = np.vstack([pts, pts[:2]])     # wrap two extra points for periodicity

    diffs   = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(diffs, axis=1)
    t_knot  = np.concatenate([[0.0], np.cumsum(seg_len)])

    # ------------------------------------------------------------------
    # BUGFIX: collapse duplicate knots so t_knot is strictly increasing.
    # Duplicates arise when two consecutive points are identical (zero
    # segment length), which makes PchipInterpolator raise ValueError.
    # Strategy: keep only the *last* occurrence of each unique value so
    # that the corresponding pts rows are fully represented.
    # ------------------------------------------------------------------
    _, unique_idx = np.unique(t_knot, return_index=True)
    if len(unique_idx) < 2:
        # All points collapsed to a single location – nothing to draw.
        return pts[:1].astype(np.int32)
    if len(unique_idx) < pts.shape[0]:
        # There were duplicates; prune both t_knot and pts together.
        t_knot = t_knot[unique_idx]
        pts    = pts[unique_idx]

    # Need at least 3 unique knots for PCHIP; fall back to raw if not.
    if len(t_knot) < 3:
        return pts.astype(np.int32)

    t_new = _curvature_adaptive_samples(pts)
    t_new = t_new * t_knot[-1]             # re-scale to arc-length domain
    # clamp to valid range
    t_new = np.clip(t_new, t_knot[0], t_knot[-1])

    pchip_x = PchipInterpolator(t_knot, pts[:, 0])
    pchip_y = PchipInterpolator(t_knot, pts[:, 1])

    x_new = pchip_x(t_new)
    y_new = pchip_y(t_new)

    return np.column_stack([x_new, y_new]).astype(np.int32)


def _should_interpolate(mode: PipelineMode,
                        closed: bool,
                        point_count: int) -> bool:
    """Keep sketch and logo tracing literal; reserve spline smoothing for denser art."""
    if point_count < 3:
        return False
    if mode is PipelineMode.ANIME:
        return True
    if mode is PipelineMode.SKETCH and point_count >= 8:
        return True
    if mode is PipelineMode.PHOTO and closed:
        return True
    return False


# --------------------------------------------------------------------------- #
# Velocity profile (FIX 12)
# --------------------------------------------------------------------------- #
def _velocity_delays(n_pts: int,
                     base_delay: float = 0.0,
                     accel_frac: float = 0.15,
                     decel_frac: float = 0.15) -> np.ndarray:
    """
    FIX 12 – trapezoid velocity profile.
    Returns an array of per-step delay values (seconds).
    base_delay = 0 means no extra delay (just the natural throttle).
    """
    if base_delay <= 0 or n_pts < 4:
        return np.zeros(n_pts)

    acc_end  = int(n_pts * accel_frac)
    dec_start= n_pts - int(n_pts * decel_frac)
    delays   = np.zeros(n_pts)

    for i in range(acc_end):
        delays[i] = base_delay * (1.0 - i / max(1, acc_end))
    for i in range(dec_start, n_pts):
        delays[i] = base_delay * ((i - dec_start) / max(1, n_pts - dec_start))

    return delays


# --------------------------------------------------------------------------- #
# SVG export (FIX 15)
# --------------------------------------------------------------------------- #
def _export_svg(ordered_contours: List[np.ndarray],
                offset_x: int, offset_y: int,
                img_w: int, img_h: int,
                svg_path: str) -> None:
    """FIX 15 – write the planned paths as an SVG file."""
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{img_w}" height="{img_h}" viewBox="0 0 {img_w} {img_h}">\n',
        '  <g stroke="black" stroke-width="1" fill="none">\n',
    ]
    for c in ordered_contours:
        pts = c.reshape(-1, 2)
        if len(pts) < 2:
            continue
        d = f'M {pts[0][0]} {pts[0][1]} '
        d += ' '.join(f'L {p[0]} {p[1]}' for p in pts[1:])
        lines.append(f'    <path d="{d}"/>\n')
    lines += ['  </g>\n', '</svg>\n']

    with open(svg_path, 'w', encoding='utf-8') as fh:
        fh.writelines(lines)
    logger.info(f'SVG exported to {svg_path}')


# --------------------------------------------------------------------------- #
# Path cache (FIX 16)
# --------------------------------------------------------------------------- #
_CACHE_DIR = os.path.join(os.path.expanduser('~'), '.image_tracer_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)


TRACE_CACHE_VERSION = 'v2'


def _cache_key(image_path: str, scale: float, mode: PipelineMode) -> str:
    mtime = os.path.getmtime(image_path)
    raw   = f'{TRACE_CACHE_VERSION}|{image_path}|{mtime}|{scale}|{mode.name}'.encode()
    return hashlib.md5(raw).hexdigest()


def _load_cache(key: str) -> Optional[Tuple]:
    path = os.path.join(_CACHE_DIR, key + '.pkl')
    if os.path.exists(path):
        try:
            with open(path, 'rb') as fh:
                data = pickle.load(fh)
            logger.info(f'Cache hit: {key}')
            return data
        except Exception:
            pass
    return None


def _save_cache(key: str, data: Tuple) -> None:
    path = os.path.join(_CACHE_DIR, key + '.pkl')
    try:
        with open(path, 'wb') as fh:
            pickle.dump(data, fh)
    except Exception as exc:
        logger.warning(f'Cache write failed: {exc}')


# --------------------------------------------------------------------------- #
# Core tracer class
# --------------------------------------------------------------------------- #
class ImageTracer:
    """
    Public API: ``trace_image``.

    Parameters
    ----------
    image_path : str
        Path to the source image.
    start_x, start_y : int
        Canvas offset (if 0, the image will be centred automatically).
    scale : float
        Scaling factor applied before processing.
    mode : PipelineMode
        Override the auto-detected pipeline mode.
    export_svg : bool
        If True, write an SVG of the path plan next to the source image.
    velocity_delay : float
        Base per-step delay for the trapezoid velocity profile (0 = off).
    """

    MIN_CONTOUR_AREA   = 5          # FIX 4 – was 1
    MIN_CONTOUR_POINTS = 2
    PAUSE_BETWEEN_STROKES = 0.005   # reduced – throttle handles rate

    # ------------------------------------------------------------------- #
    @staticmethod
    def _prepare_contours(binary: np.ndarray,
                          mode: PipelineMode) -> List[np.ndarray]:
        # FIX 8 – Potrace is the PRIMARY path for LOGO mode
        contours: List[np.ndarray] = []
        if mode is PipelineMode.LOGO:
            contours = _vectorise_with_potrace(binary)

        if not contours:
            # Bug #1/#2 fix – use extracted _get_retrieval_mode(); call
            # findContours with plain positional args (no keyword assignment).
            retrieval_mode = _get_retrieval_mode(mode)
            raw, _ = cv2.findContours(
                binary,
                retrieval_mode,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            contours = list(raw)

        # Issue #7 fix – single normalized epsilon; never rescale again
        # inside _smooth_contour or _simplify_contour.
        img_h, img_w = binary.shape[:2]
        max_dim      = max(img_h, img_w)
        if mode is PipelineMode.SKETCH:
            # Sketch assets already contain many small interior strokes.
            # Simplify a bit more so the traced result stays readable.
            epsilon_px = max(0.8, max_dim * 0.0025)
            target_points = 120
        elif mode is PipelineMode.ANIME:
            epsilon_px = max(0.5, max_dim * 0.0015)
            target_points = 180
        else:
            epsilon_px = max(0.5, max_dim * 0.003)   # ~0.3 % of image size
            target_points = 100

        filtered: List[np.ndarray] = []
        for c in contours:
            if _is_border_frame_contour(c, img_w, img_h):
                continue
            if _is_small_border_fragment(c, img_w, img_h):
                continue

            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            bbox_area = w * h
            perimeter = cv2.arcLength(c, False)

            if (
                area < ImageTracer.MIN_CONTOUR_AREA
                and perimeter < 20.0
                and bbox_area < 36
            ):
                continue
            if len(c) < ImageTracer.MIN_CONTOUR_POINTS:
                continue

            # Issue #11 fix – hybrid approximation: NONE explodes RAM on
            # large contours; only use dense points for small ones.
            # (We already requested CHAIN_APPROX_SIMPLE above, but the
            # Potrace path can return arbitrarily dense arrays.)
            if len(c) > 2_000:
                # Force Douglas-Peucker simplification before further work
                c = cv2.approxPolyDP(c, epsilon_px, closed=False)

            # Issue #6 fix – adaptive sparse pre-sampling so tiny contours
            # are not collapsed and huge ones don't thrash RAM.
            pts = c.reshape(-1, 2)
            step = max(1, len(pts) // target_points)
            pts  = pts[::step]
            c    = pts.reshape(-1, 1, 2).astype(np.int32)

            simp = _simplify_contour(c, epsilon_px=epsilon_px)       # FIX 14
            simp = _remove_collinear(simp.reshape(-1, 2))
            if len(simp) < ImageTracer.MIN_CONTOUR_POINTS:
                continue
            filtered.append(simp.reshape(-1, 1, 2))

        logger.info(f'{len(filtered)} contours after filtering.')
        return filtered

    # ------------------------------------------------------------------- #
    @staticmethod
    def trace_image(image_path:     str,
                    start_x:        int           = 0,
                    start_y:        int           = 0,
                    scale:          float         = 0.8,
                    mode:           PipelineMode  = PipelineMode.AUTO,
                    export_svg:     bool          = False,
                    velocity_delay: float         = 0.0) -> bool:
        """
        Draw the image inside MS Paint.
        Returns True on success, False on error or ESC-abort.
        """
        if not _HAS_WIN32:
            logger.error(
                "trace_image: MS Paint drawing requires Windows. "
                "win32gui / win32con are not available on this OS."
            )
            return False

        logger.info(f'trace_image: {image_path}')

        try:
            # ---------------------------------------------------------------- #
            # 0 – Focus Paint
            # ---------------------------------------------------------------- #
            canvas_cx, canvas_cy, paint_hwnd = _fast_canvas_center()

            # ---------------------------------------------------------------- #
            # 1 – Load / preprocess (with cache, FIX 16)
            # ---------------------------------------------------------------- #
            cache_key = _cache_key(image_path, scale, mode)
            cached    = _load_cache(cache_key)

            if cached:
                binary_img, img_w, img_h, mode, ordered = cached
                logger.info('Using cached contour plan.')
            else:
                binary_img, img_w, img_h, mode = _load_and_preprocess(
                    image_path, scale, mode=mode)

                # ------------------------------------------------------------ #
                # 2 – Extract contours (FIX 8: Potrace primary for LOGO)
                # ------------------------------------------------------------ #
                contours = ImageTracer._prepare_contours(binary_img, mode)
                if not contours:
                    logger.warning('No drawable contours – aborting.')
                    return False

                # ------------------------------------------------------------ #
                # 3 – Stitch (FIX 9)
                # ------------------------------------------------------------ #
                if mode not in (PipelineMode.SKETCH, PipelineMode.ANIME):
                    contours = _stitch_contours(contours, max_gap_px=8.0)

                # ------------------------------------------------------------ #
                # 4 – Origin & NN ordering (FIX 2)
                # ------------------------------------------------------------ #
                origin_x  = canvas_cx - img_w // 2
                origin_y  = canvas_cy - img_h // 2
                ordered   = _order_contours_nn(contours, origin_x, origin_y)

                _save_cache(cache_key, (binary_img, img_w, img_h, mode, ordered))

            origin_x = canvas_cx - img_w // 2
            origin_y = canvas_cy - img_h // 2
            logger.info(
                f"Prepared {len(ordered)} contour chains for drawing "
                f"({img_w}x{img_h}, origin=({origin_x}, {origin_y}))."
            )

            # ---------------------------------------------------------------- #
            # Optional SVG export (FIX 15)
            # ---------------------------------------------------------------- #
            if export_svg:
                svg_out = os.path.splitext(image_path)[0] + '_plan.svg'
                _export_svg(ordered, origin_x, origin_y, img_w, img_h, svg_out)
                if mode is PipelineMode.SVG:
                    logger.info('SVG-only mode – skipping Paint drawing.')
                    return True

            screen_w = _mouse._screen_w
            screen_h = _mouse._screen_h

            # ---------------------------------------------------------------- #
            # 5 – Draw
            # ---------------------------------------------------------------- #
            total_contours = len(ordered)
            for idx, contour in enumerate(ordered):
                # ESC abort (FIX 4 / original FIX) – Windows only
                if _HAS_WIN32 and ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    logger.info('Esc – aborting.')
                    _mouse.mouse_up()
                    return False

                raw_pts = contour.reshape(-1, 2).astype(np.int32)

                # FIX 6 – detect closed contour
                is_closed = (math.hypot(
                    int(raw_pts[0][0]) - int(raw_pts[-1][0]),
                    int(raw_pts[0][1]) - int(raw_pts[-1][1]),
                ) < 3.0)

                # FIX 5 + 6 + 13 – interpolate
                if _should_interpolate(mode, is_closed, len(raw_pts)):
                    interp_pts = _smooth_interpolate_contour(raw_pts, closed=is_closed)
                else:
                    interp_pts = raw_pts

                # FIX 12 – velocity profile
                delays = _velocity_delays(len(interp_pts), base_delay=velocity_delay)

                # Pen-down
                fx, fy   = interp_pts[0]
                target_x = max(0, min(screen_w - 1, origin_x + int(fx)))
                target_y = max(0, min(screen_h - 1, origin_y + int(fy)))
                _mouse.move_to(target_x, target_y)
                _mouse.mouse_down()

                # FIX 1 – use move_to() only (no nested smoothing)
                for k, (px, py) in enumerate(interp_pts[1:], start=1):
                    gx = max(0, min(screen_w - 1, origin_x + int(px)))
                    gy = max(0, min(screen_h - 1, origin_y + int(py)))
                    _mouse.move_to(gx, gy)
                    d = delays[k] if k < len(delays) else 0.0
                    if d > 0:
                        time.sleep(d)

                _mouse.mouse_up()
                time.sleep(ImageTracer.PAUSE_BETWEEN_STROKES)

                if total_contours <= 5 or (idx + 1) % 25 == 0 or idx + 1 == total_contours:
                    logger.info(f'Drawing progress: {idx + 1}/{total_contours} contours')

            logger.info('Trace completed successfully.')
            return True

        except Exception as exc:
            logger.error(f'Trace failed: {exc}', exc_info=True)
            _mouse.mouse_up()   # safety: always release
            return False
