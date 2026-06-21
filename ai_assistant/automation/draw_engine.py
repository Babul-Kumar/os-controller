from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, Future

import cv2
import numpy as np
import pyautogui
import requests

from utils.helpers import setup_logger
from automation.file_finder import FileFinder
from automation.image_tracer import (
    ImageTracer,
    PipelineMode,
    _is_border_frame_contour,
    _load_and_preprocess,
    _stitch_contours,
)

logger = setup_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# Cache‑busting version
ASSET_VERSION = "v10"
PREPROCESS_VERSION = "v7"
TRACER_VERSION = "v6"
RENDERER_VERSION = "v4"

# Cache management
MAX_CACHE_SIZE_MB = 500
MAX_CACHE_AGE_DAYS = 30

# Remote generation guardrails
REMOTE_IMAGE_ATTEMPTS = 3
REMOTE_IMAGE_CONNECT_TIMEOUT_S = 5
REMOTE_IMAGE_READ_TIMEOUT_S = 8
REMOTE_IMAGE_DEADLINE_S = 14
REMOTE_IMAGE_RETRY_DELAY_S = 1.5
OUTLINE_MAX_CONTOURS = 8
OUTLINE_MIN_AREA_RATIO = 0.0015

# Polarity threshold
POLARITY_THRESHOLD = 0.5
CLOSURE_THRESHOLD = 5.0  # Pixels

# Interpolation types (FIX-12)
class InterpolationType(Enum):
    NONE = "none"
    LINEAR = "linear"
    CATMULL_ROM = "catmull_rom"
    BEZIER = "bezier"


class RenderingBackend(Enum):
    SENDINPUT = "sendinput"
    PYAUTOGUI = "pyautogui"
    SVG = "svg"


class RetrievalStrategy(Enum):
    """FIX-8: Dynamic retrieval mode selection"""
    EXTERNAL = "external"  # Outer contours only
    CCOMP = "ccomp"        # Two-level hierarchy
    TREE = "tree"          # Full hierarchy


class ApproximationStrategy(Enum):
    """FIX-11: Dynamic approximation method"""
    SIMPLE = "simple"   # CHAIN_APPROX_SIMPLE
    NONE = "none"       # CHAIN_APPROX_NONE
    TC89_L1 = "tc89_l1" # CHAIN_APPROX_TC89_L1


# ══════════════════════════════════════════════════════════════════════════════
# §1  Pipeline Configuration Objects
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PreprocessingConfig:
    """Mode‑aware preprocessing settings."""
    denoise_strength: float = 10.0
    denoise_type: str = "nlmeans"
    denoise_kernel: int = 3  # FIX-9: Smaller kernel for sketches
    apply_clahe: bool = False
    clahe_clip: float = 2.0
    apply_otsu: bool = False
    apply_adaptive_threshold: bool = False
    adaptive_block_size: int = 11
    adaptive_c: int = 2
    sharpen_method: str = "none"
    upscale_min_dim: int = 600
    resize_before_threshold: bool = True


@dataclass
class QualityConfig:
    """Mode‑aware quality validation thresholds."""
    min_contrast: float = 30.0
    min_edge_density: float = 0.02
    max_components: int = 500
    min_binary_ratio: float = 0.05
    max_binary_ratio: float = 0.85
    max_frag_ratio: float = 0.60
    min_contours: int = 5
    min_contour_coverage: float = 0.01
    # FIX-2: Perimeter-based coverage threshold
    min_perimeter_coverage: float = 5.0
    use_adaptive_validation: bool = True
    # FIX-7: Don't early-return, but reduce strictness
    adaptive_strictness_reduction: float = 0.7


@dataclass
class TracingPolicy:
    """Tracing policy configuration."""
    simplify_epsilon: float = 1.5
    simplify_epsilon_scale: float = 0.001
    stitch_threshold: int = 10
    interpolate: bool = True
    interpolation_type: InterpolationType = InterpolationType.LINEAR
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.CCOMP  # FIX-8
    approximation_strategy: ApproximationStrategy = ApproximationStrategy.SIMPLE  # FIX-11
    smooth_before_curvature: bool = True
    curvature_smooth_epsilon: float = 0.001
    curvature_sample_sparse: bool = True  # FIX-5
    curvature_sample_step: int = 3  # FIX-5


@dataclass
class RenderingConfig:
    """Backend-specific rendering limits."""
    backend: RenderingBackend = RenderingBackend.SENDINPUT
    max_points: int = 300000
    max_draw_time: int = 1200
    interpolation_overhead: float = 1.5
    pen_lift_time_ms: int = 200
    optimize_path: bool = True  # FIX-14


@dataclass
class PipelineConfig:
    """Complete pipeline configuration for a mode."""
    preprocess: PreprocessingConfig = field(default_factory=PreprocessingConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    tracing: TracingPolicy = field(default_factory=TracingPolicy)
    rendering: RenderingConfig = field(default_factory=RenderingConfig)
    trace_scale: float = 1.0


@dataclass
class DrawableCandidate:
    """A prepared asset that is safe enough to trace in Paint."""
    processed_path: Path
    mode: PipelineMode
    trace_source: Path
    density: Dict[str, Any]
    estimate: Dict[str, float]


# Mode‑specific configurations
PIPELINE_CONFIGS = {
    PipelineMode.SKETCH: PipelineConfig(
        preprocess=PreprocessingConfig(
            denoise_strength=5.0,
            denoise_type="median",
            denoise_kernel=3,  # FIX-9: Gentler kernel
            apply_adaptive_threshold=True,
            adaptive_block_size=11,
            adaptive_c=2,
            sharpen_method="mild",
            upscale_min_dim=900,
            resize_before_threshold=True,
        ),
        quality=QualityConfig(
            min_contrast=20.0,
            max_components=2000,
            min_binary_ratio=0.02,
            max_binary_ratio=0.80,
            max_frag_ratio=0.70,
            min_contours=5,  # Lowered for sketches
            min_perimeter_coverage=3.0,  # Recalibrated for normalized perimeter coverage
            use_adaptive_validation=True,
            adaptive_strictness_reduction=0.7,
        ),
        tracing=TracingPolicy(
            simplify_epsilon=1.2,
            simplify_epsilon_scale=0.0008,
            stitch_threshold=8,
            interpolate=True,
            interpolation_type=InterpolationType.CATMULL_ROM,
            retrieval_strategy=RetrievalStrategy.CCOMP,
            approximation_strategy=ApproximationStrategy.NONE,  # FIX-11: Preserve detail
            smooth_before_curvature=True,
            curvature_smooth_epsilon=0.0008,
            curvature_sample_sparse=True,
            curvature_sample_step=3,
        ),
        trace_scale=1.2,
    ),
    PipelineMode.LOGO: PipelineConfig(
        preprocess=PreprocessingConfig(
            denoise_strength=15.0,
            denoise_type="gaussian",
            denoise_kernel=5,
            apply_clahe=True,
            apply_otsu=True,
            sharpen_method="aggressive",
            upscale_min_dim=600,
            resize_before_threshold=True,
        ),
        quality=QualityConfig(
            min_contrast=40.0,
            max_components=100,
            max_frag_ratio=0.30,
            min_contours=3,
            min_perimeter_coverage=8.0,
            use_adaptive_validation=False,
        ),
        tracing=TracingPolicy(
            simplify_epsilon=2.0,
            simplify_epsilon_scale=0.002,
            stitch_threshold=15,
            interpolate=False,
            interpolation_type=InterpolationType.LINEAR,
            retrieval_strategy=RetrievalStrategy.EXTERNAL,
            approximation_strategy=ApproximationStrategy.SIMPLE,
            smooth_before_curvature=False,
        ),
        trace_scale=0.8,
    ),
    PipelineMode.AUTO: PipelineConfig(
        preprocess=PreprocessingConfig(
            denoise_strength=8.0,
            denoise_type="nlmeans",
            denoise_kernel=3,
            apply_clahe=True,
            apply_adaptive_threshold=True,
            upscale_min_dim=750,
            resize_before_threshold=True,
        ),
        quality=QualityConfig(
            min_perimeter_coverage=4.5,
            use_adaptive_validation=True,
        ),
        tracing=TracingPolicy(
            simplify_epsilon=1.5,
            simplify_epsilon_scale=0.001,
            stitch_threshold=10,
            interpolate=True,
            interpolation_type=InterpolationType.LINEAR,
            retrieval_strategy=RetrievalStrategy.CCOMP,
            approximation_strategy=ApproximationStrategy.SIMPLE,
            smooth_before_curvature=True,
        ),
        trace_scale=1.0,
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# §2  Utility helpers
# ══════════════════════════════════════════════════════════════════════════════

def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w\-_]', '_', name.strip().lower())


def _is_generated_asset_stem(stem: str) -> bool:
    return bool(re.search(r"_[0-9a-f]{8,12}_v\d+$", stem))


def _is_preprocessed_asset(image_path: Path) -> bool:
    return "_preprocessed" in image_path.stem


def _get_raw_asset_path(image_path: Path) -> Path:
    if not _is_preprocessed_asset(image_path):
        return image_path

    raw_stem = re.sub(r"_preprocessed(?:_[a-z]+)?$", "", image_path.stem)
    candidate = image_path.with_name(raw_stem + image_path.suffix)
    return candidate if candidate.exists() else image_path


def _processed_asset_path(image_path: Path, mode: PipelineMode) -> Path:
    raw_path = _get_raw_asset_path(image_path)
    return raw_path.with_stem(f"{raw_path.stem}_preprocessed_{mode.name.lower()}")


def _odd_kernel_size(value: int, minimum: int = 3) -> int:
    size = max(minimum, int(value))
    return size if size % 2 == 1 else size + 1


def _get_retrieval_mode(strategy: RetrievalStrategy) -> int:
    """FIX-8: Convert strategy to OpenCV constant."""
    if strategy == RetrievalStrategy.EXTERNAL:
        return cv2.RETR_EXTERNAL
    elif strategy == RetrievalStrategy.CCOMP:
        return cv2.RETR_CCOMP
    else:
        return cv2.RETR_TREE


def _get_approx_method(strategy: ApproximationStrategy) -> int:
    """FIX-11: Convert strategy to OpenCV constant."""
    if strategy == ApproximationStrategy.SIMPLE:
        return cv2.CHAIN_APPROX_SIMPLE
    elif strategy == ApproximationStrategy.NONE:
        return cv2.CHAIN_APPROX_NONE
    else:
        return cv2.CHAIN_APPROX_TC89_L1


def _get_config_hash(config: PipelineConfig) -> str:
    """FIX-15: Include runtime constants in hash."""
    config_dict = {
        "preprocess": {
            "denoise_strength": config.preprocess.denoise_strength,
            "denoise_type": config.preprocess.denoise_type,
            "denoise_kernel": config.preprocess.denoise_kernel,
            "apply_clahe": config.preprocess.apply_clahe,
            "apply_adaptive_threshold": config.preprocess.apply_adaptive_threshold,
            "adaptive_block_size": config.preprocess.adaptive_block_size,
            "adaptive_c": config.preprocess.adaptive_c,
            "sharpen_method": config.preprocess.sharpen_method,
            "upscale_min_dim": config.preprocess.upscale_min_dim,
            "resize_before_threshold": config.preprocess.resize_before_threshold,
        },
        "tracing": {
            "simplify_epsilon": config.tracing.simplify_epsilon,
            "simplify_epsilon_scale": config.tracing.simplify_epsilon_scale,
            "interpolate": config.tracing.interpolate,
            "interpolation_type": config.tracing.interpolation_type.value,
            "retrieval_strategy": config.tracing.retrieval_strategy.value,
            "approximation_strategy": config.tracing.approximation_strategy.value,
            "curvature_sample_sparse": config.tracing.curvature_sample_sparse,
            "curvature_sample_step": config.tracing.curvature_sample_step,
        },
        "rendering": {
            "max_points": config.rendering.max_points,
            "max_draw_time": config.rendering.max_draw_time,
            "interpolation_overhead": config.rendering.interpolation_overhead,
            "optimize_path": config.rendering.optimize_path,
        },
        "runtime": {
            "ASSET_VERSION": ASSET_VERSION,
            "PREPROCESS_VERSION": PREPROCESS_VERSION,
            "TRACER_VERSION": TRACER_VERSION,
            "RENDERER_VERSION": RENDERER_VERSION,
        },
    }
    config_str = json.dumps(config_dict, sort_keys=True)
    return hashlib.md5(config_str.encode()).hexdigest()[:8]


def _prompt_hash(prompt: str, mode: PipelineMode, config: PipelineConfig) -> str:
    config_hash = _get_config_hash(config)
    content = f"{prompt}|{mode.name}|{ASSET_VERSION}|{PREPROCESS_VERSION}|{TRACER_VERSION}|{config_hash}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def _versioned_asset_path(safe_name: str, mode: PipelineMode, prompt: str, config: PipelineConfig) -> Path:
    phash = _prompt_hash(prompt, mode, config)
    filename = f"{safe_name}_{mode.name.lower()}_{phash}_{ASSET_VERSION}.png"
    return ASSETS_DIR / filename


def _manage_cache_size(max_size_mb: int = MAX_CACHE_SIZE_MB, max_age_days: int = MAX_CACHE_AGE_DAYS) -> None:
    try:
        total_size = 0
        file_info = []
        now = time.time()
        
        for f in ASSETS_DIR.glob("*.png"):
            if f.is_file():
                if now - f.stat().st_atime < 300:
                    continue
                    
                size = f.stat().st_size
                mtime = f.stat().st_mtime
                age_days = (now - mtime) / 86400
                
                if age_days > max_age_days:
                    f.unlink()
                    continue
                
                total_size += size
                file_info.append((f, size, mtime))
        
        if total_size > max_size_mb * 1024 * 1024:
            file_info.sort(key=lambda x: x[2])
            for f, size, _ in file_info:
                if total_size <= max_size_mb * 1024 * 1024:
                    break
                f.unlink()
                total_size -= size
    except Exception as exc:
        logger.warning(f"Cache cleanup failed: {exc}")


def _get_pipeline_config(mode: PipelineMode) -> PipelineConfig:
    return PIPELINE_CONFIGS.get(mode, PIPELINE_CONFIGS[PipelineMode.AUTO])


# ══════════════════════════════════════════════════════════════════════════════
# §3  Mode detection
# ══════════════════════════════════════════════════════════════════════════════

_MODE_SCORES: List[Tuple[frozenset, PipelineMode, int]] = [
    (frozenset({"sketch", "anime", "manga", "portrait", "detailed", "realistic", "texture"}),
     PipelineMode.SKETCH, 5),
    (frozenset({"logo", "icon", "symbol", "brand", "seal", "crest"}),
     PipelineMode.LOGO, 5),
    (frozenset({
        "cat", "dog", "rabbit", "bird", "fish", "tiger", "lion", "wolf", "bear",
        "fox", "horse", "elephant", "dragon", "snake", "tree", "house", "butterfly",
        "flower", "car",
    }), PipelineMode.SKETCH, 4),
    (frozenset({"star", "heart", "flag", "badge", "banner", "emblem"}),
     PipelineMode.AUTO, 2),
]

FALLBACK_MAP = {
    PipelineMode.SKETCH: [PipelineMode.AUTO, PipelineMode.LOGO],
    PipelineMode.LOGO: [PipelineMode.SKETCH, PipelineMode.AUTO],
    PipelineMode.AUTO: [PipelineMode.SKETCH, PipelineMode.LOGO],
}


def _tokenize(text: str) -> Set[str]:
    return set(re.findall(r'\w+', text.lower()))


def _detect_best_mode(shape_name: str) -> PipelineMode:
    tokens = _tokenize(shape_name)
    scores = {PipelineMode.SKETCH: 0, PipelineMode.LOGO: 0, PipelineMode.AUTO: 0}
    
    for keyword_set, mode, score in _MODE_SCORES:
        if tokens & keyword_set:
            scores[mode] += score
    
    best_mode = max(scores, key=scores.get)
    return best_mode if scores[best_mode] > 0 else PipelineMode.AUTO


def _build_attempt_chain(primary: PipelineMode) -> List[PipelineMode]:
    seen: Set[PipelineMode] = {primary}
    chain = [primary]
    for fb in FALLBACK_MAP.get(primary, []):
        if fb not in seen:
            chain.append(fb)
            seen.add(fb)
    return chain


def _get_trace_source_path(image_path: Path, mode: PipelineMode) -> Path:
    """
    Choose the best source for tracing.
    Sketches generally benefit from tracing the already-cleaned binary asset,
    while other modes can still prefer the original source image when present.
    """
    if not _is_preprocessed_asset(image_path):
        return image_path

    if mode is PipelineMode.SKETCH:
        return image_path

    raw_path = _get_raw_asset_path(image_path)
    return raw_path if raw_path.exists() else image_path


def _find_local_asset(query: str, mode: PipelineMode) -> Optional[Path]:
    """
    Prefer bundled repo assets over generated network assets when they exist.
    This gives more stable results for common subjects like `cat`.
    """
    safe_name = _safe_filename(query)
    if not safe_name:
        return None

    candidates = [p for p in ASSETS_DIR.glob("*.png") if "_preprocessed" not in p.stem]
    if not candidates:
        return None

    ranked: List[Tuple[int, float, Path]] = []
    for path in candidates:
        stem = path.stem.lower()
        if _is_generated_asset_stem(stem) or stem.endswith("_outline") or stem.startswith("_exp_") or stem.startswith("_merge_"):
            continue

        score = -1

        # Prefer manually curated non-versioned assets.
        if stem == f"{safe_name}_image":
            score = 130 if mode is PipelineMode.SKETCH else 110
        elif stem == safe_name:
            score = 120 if mode is not PipelineMode.SKETCH else 115
        elif stem.startswith(f"{safe_name}_sketch"):
            score = 105 if mode is PipelineMode.SKETCH else 90
        elif stem.startswith(f"{safe_name}_logo"):
            score = 105 if mode is PipelineMode.LOGO else 70
        elif stem.startswith(f"{safe_name}_"):
            score = 80
        elif safe_name in stem and "_v" not in stem:
            score = 60
        elif safe_name in stem:
            score = 40

        if score >= 0:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            ranked.append((score, mtime, path))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (-item[0], -item[1], item[2].name))
    return ranked[0][2]


# ══════════════════════════════════════════════════════════════════════════════
# §4  Polarity detection (histogram-based)
# ══════════════════════════════════════════════════════════════════════════════

def _detect_threshold_polarity_histogram(img: np.ndarray) -> int:
    """Histogram-based polarity detection."""
    hist = cv2.calcHist([img], [0], None, [256], [0, 256])
    dark_pixels = np.sum(hist[:128])
    bright_pixels = np.sum(hist[128:])
    dark_ratio = dark_pixels / (dark_pixels + bright_pixels + 1e-6)
    
    if dark_ratio < POLARITY_THRESHOLD:
        return cv2.THRESH_BINARY_INV
    return cv2.THRESH_BINARY


def _try_both_polarities(img: np.ndarray, mode: PipelineMode) -> Tuple[np.ndarray, int]:
    """
    FIX-3: Try both binary polarities and choose best.
    Returns (binary_image, chosen_polarity)
    """
    best_binary = None
    best_score = -1
    best_polarity = cv2.THRESH_BINARY
    
    for polarity in [cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV]:
        _, binary = cv2.threshold(img, 0, 255, polarity | cv2.THRESH_OTSU)
        retrieval_mode = _get_retrieval_mode(
            _get_pipeline_config(mode).tracing.retrieval_strategy
        )
        
        # Score: contour count + coverage
        contours, _ = cv2.findContours(
            binary,
            retrieval_mode,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        contour_count = len(contours)
        
        if contour_count == 0:
            continue
        
        total_px = img.shape[0] * img.shape[1]
        foreground_px = np.count_nonzero(binary)
        coverage = foreground_px / total_px
        
        # Prefer moderate coverage (not too sparse, not too filled)
        target_coverage = {
            PipelineMode.SKETCH: 0.08,
            PipelineMode.LOGO: 0.25,
            PipelineMode.AUTO: 0.18,
        }

        coverage_score = 1.0 - abs(coverage - target_coverage[mode])
        
        # Prefer more contours (more detail)
        contour_score = min(contour_count / 100, 1.0)
        
        score = coverage_score * 0.6 + contour_score * 0.4
        
        if score > best_score:
            best_score = score
            best_binary = binary
            best_polarity = polarity
    
    if best_binary is None:
        _, best_binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        best_polarity = cv2.THRESH_BINARY
    
    return best_binary, best_polarity


def _dynamic_adaptive_block_size(h: int, w: int) -> int:
    block = max(11, (min(h, w) // 40) | 1)
    return block if block % 2 == 1 else block + 1


# ══════════════════════════════════════════════════════════════════════════════
# §5  Quality validation (FIX-1, FIX-2, FIX-3, FIX-7)
# ══════════════════════════════════════════════════════════════════════════════

def _is_image_quality_good(image_path: Path, mode: PipelineMode) -> bool:
    """Multi‑metric quality gate with FIX-1, FIX-2, FIX-3, FIX-7."""
    config = _get_pipeline_config(mode)
    quality_config = config.quality
    
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False
        
        # 1. Contrast
        contrast = float(np.std(img))
        if contrast < quality_config.min_contrast:
            logger.debug(f"Quality FAIL – contrast {contrast:.2f}")
            return False
        
        # FIX-1 & FIX-3: Polarity-aware thresholding with both polarities
        binary, used_polarity = _try_both_polarities(img, mode)
        
        # FIX-8: Use config's retrieval mode
        retrieval_mode = _get_retrieval_mode(config.tracing.retrieval_strategy)
        contours, hierarchy = cv2.findContours(
            binary, retrieval_mode, cv2.CHAIN_APPROX_SIMPLE
        )
        
        total_px = img.shape[0] * img.shape[1]
        
        # FIX-2: Perimeter-based coverage for thin line art
        total_perimeter = sum(cv2.arcLength(c, True) for c in contours)
        perimeter_coverage = total_perimeter / math.sqrt(total_px) if total_px > 0 else 0
        
        # Also compute area coverage for comparison
        contour_area = sum(cv2.contourArea(c) for c in contours)
        area_coverage = contour_area / total_px if total_px > 0 else 0
        
        logger.debug(f"Coverage: perimeter={perimeter_coverage:.4f}, area={area_coverage:.4f}")
        
        # FIX-7: Don't early-return; run all checks with reduced strictness if adaptive
        strictness = quality_config.adaptive_strictness_reduction if quality_config.use_adaptive_validation else 1.0
        
        # Check perimeter coverage (primary metric for sketches)
        min_perimeter = quality_config.min_perimeter_coverage * strictness
        if perimeter_coverage < min_perimeter and area_coverage < quality_config.min_contour_coverage:
            logger.debug(f"Quality FAIL – coverage perimeter={perimeter_coverage:.4f} < {min_perimeter}")
            return False
        
        # Check binary ratio
        dark_ratio = area_coverage
        if not (quality_config.min_binary_ratio <= dark_ratio <= quality_config.max_binary_ratio * (1/strictness if strictness < 1 else 1)):
            logger.debug(f"Quality FAIL – binary ratio {dark_ratio:.3f}")
            return False
        
        # Check fragmentation
        if contours:
            short = sum(1 for c in contours if cv2.arcLength(c, False) < 10)
            frag_ratio = short / len(contours)
            max_frag = quality_config.max_frag_ratio * (1.5 if strictness < 1 else 1)
            if frag_ratio > max_frag:
                logger.debug(f"Quality FAIL – frag_ratio {frag_ratio:.3f}")
                return False
        
        # Check component count
        num_labels, _ = cv2.connectedComponents(binary)
        component_count = num_labels - 1
        max_components = quality_config.max_components * (2 if strictness < 1 else 1)
        if component_count > max_components:
            logger.debug(f"Quality FAIL – {component_count} components > {max_components}")
            return False
        
        logger.debug(f"Quality OK: contrast={contrast:.1f}, contours={len(contours)}, "
                    f"perimeter_coverage={perimeter_coverage:.4f}")
        return True
        
    except Exception as exc:
        logger.error(f"Exception during quality check: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# §6  Contour processing (FIX-4, FIX-5, FIX-10)
# ══════════════════════════════════════════════════════════════════════════════

def _is_contour_closed(contour: np.ndarray, threshold: float = CLOSURE_THRESHOLD) -> bool:
    """FIX-4: Detect if contour is closed by checking start-end distance."""
    if len(contour) < 3:
        return False
    start = contour[0][0] if len(contour[0].shape) > 1 else contour[0]
    end = contour[-1][0] if len(contour[-1].shape) > 1 else contour[-1]
    distance = np.linalg.norm(start - end)
    return distance < threshold


def _smooth_contour(contour: np.ndarray, epsilon_px: float) -> np.ndarray:
    """Smooth contour with closure detection using pixel-space epsilon."""
    if len(contour) < 5:
        return contour

    contour = np.ascontiguousarray(contour)
    if contour.dtype not in (np.int32, np.float32):
        contour = contour.astype(np.float32)

    closed = _is_contour_closed(contour)
    return cv2.approxPolyDP(contour, epsilon=epsilon_px, closed=closed)


def _compress_large_contour(contour: np.ndarray) -> np.ndarray:
    """Approximate CHAIN_APPROX_SIMPLE behavior for oversized CHAIN_APPROX_NONE contours."""
    if len(contour) <= 2:
        return contour

    compressed = [contour[0]]

    for i in range(1, len(contour) - 1):
        prev_point = contour[i - 1][0]
        point = contour[i][0]
        next_point = contour[i + 1][0]

        incoming = np.sign(point - prev_point)
        outgoing = np.sign(next_point - point)
        if not np.array_equal(incoming, outgoing):
            compressed.append(contour[i])

    compressed.append(contour[-1])
    return np.asarray(compressed, dtype=contour.dtype)


def _prepare_contours_for_analysis(
    contours: List[np.ndarray],
    strategy: ApproximationStrategy,
) -> List[np.ndarray]:
    """Cap oversized raw contours without sacrificing detail on small contours."""
    if strategy != ApproximationStrategy.NONE:
        return contours

    prepared = []
    for contour in contours:
        if len(contour) > 2000:
            prepared.append(_compress_large_contour(contour))
        else:
            prepared.append(contour)
    return prepared


def _compute_curvature_proxy(contour: np.ndarray, config: TracingPolicy, max_dim: float = None) -> float:
    """
    FIX-5: Sparse sampling for curvature analysis
    FIX-10: Scale-aware smoothing
    """
    if len(contour) < 5:
        return 0.0
    
    # FIX-5: Sparse sampling
    if config.curvature_sample_sparse:
        step = max(1, len(contour) // 100)
        contour = np.ascontiguousarray(contour[::step])
    
    if len(contour) < 5:
        return 0.0

    # FIX-4 & FIX-10: Smooth once with normalized epsilon converted to pixels
    if config.smooth_before_curvature:
        epsilon_px = config.curvature_smooth_epsilon
        if max_dim is not None:
            epsilon_px = max_dim * config.curvature_smooth_epsilon
        contour = _smooth_contour(contour, epsilon_px)
    
    curvature_proxies = []
    for i in range(len(contour)):
        p1 = contour[i][0] if len(contour[i].shape) > 1 else contour[i]
        p2 = contour[(i+1) % len(contour)][0] if len(contour[(i+1) % len(contour)].shape) > 1 else contour[(i+1) % len(contour)]
        p3 = contour[(i+2) % len(contour)][0] if len(contour[(i+2) % len(contour)].shape) > 1 else contour[(i+2) % len(contour)]
        
        v1 = p2 - p1
        v2 = p3 - p2
        
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 > 0 and norm2 > 0:
            dot = np.dot(v1, v2)
            cos_angle = np.clip(dot / (norm1 * norm2), -1.0, 1.0)
            curvature_proxy = 1.0 - cos_angle
            curvature_proxies.append(curvature_proxy)
    
    return float(np.mean(curvature_proxies)) if curvature_proxies else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# §7  Contour ordering optimization (FIX-6, FIX-14)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_centroids(contours: List[np.ndarray]) -> List[Tuple[float, float]]:
    """Compute centroid for each contour."""
    centroids = []
    for c in contours:
        M = cv2.moments(c)
        if M["m00"] != 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            centroids.append((cx, cy))
        else:
            pts = c.reshape(-1, 2)
            cx = float(np.mean(pts[:, 0]))
            cy = float(np.mean(pts[:, 1]))
            centroids.append((cx, cy))
    return centroids


def _order_contours_nearest_neighbor(contours: List[np.ndarray]) -> List[np.ndarray]:
    """FIX-6 & FIX-14: Order contours by nearest neighbor (simple TSP heuristic)."""
    if len(contours) <= 1:
        return contours
    
    centroids = _compute_centroids(contours)
    ordered = []
    used = [False] * len(contours)
    
    # Start with largest contour (likely the main subject)
    areas = [cv2.contourArea(c) for c in contours]
    start_idx = np.argmax(areas)
    
    ordered.append(contours[start_idx])
    used[start_idx] = True
    current = centroids[start_idx]
    
    while len(ordered) < len(contours):
        # Find nearest unused centroid
        best_idx = -1
        best_dist = float('inf')
        for i, (used_flag, centroid) in enumerate(zip(used, centroids)):
            if not used_flag:
                dist = np.linalg.norm(np.array(centroid) - np.array(current))
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
        
        if best_idx >= 0:
            ordered.append(contours[best_idx])
            used[best_idx] = True
            current = centroids[best_idx]
    
    return ordered


# ══════════════════════════════════════════════════════════════════════════════
# §8  Contour analysis (FIX-6, FIX-13)
# ══════════════════════════════════════════════════════════════════════════════

def _analyze_contour_density(image_path: Path, mode: PipelineMode) -> Dict[str, Any]:
    """Analyze contour density with ordering and curvature weighting."""
    config = _get_pipeline_config(mode)
    tracing_config = config.tracing
    
    try:
        binary, img_w, img_h, effective_mode = _load_and_preprocess(
            str(image_path),
            scale=config.trace_scale,
            mode=mode,
        )

        # Reuse the same contour-preparation pipeline as the real tracer so
        # draw-time estimation reflects what Paint will actually receive.
        contours = ImageTracer._prepare_contours(binary, effective_mode)
        
        if not contours:
            return {"total_contours": 0, "total_points": 0}

        if effective_mode not in (PipelineMode.SKETCH, PipelineMode.ANIME):
            contours = _stitch_contours(contours, max_gap_px=8.0)

        max_dim = max(img_h, img_w)
        scale_epsilon = max_dim * tracing_config.simplify_epsilon_scale
        
        # FIX-6: Order contours for travel distance
        ordered_contours = _order_contours_nearest_neighbor(contours)
        centroids = _compute_centroids(ordered_contours)
        
        # FIX-6: Travel distance with optimal ordering
        travel_distance = 0
        if len(centroids) > 1:
            for i in range(len(centroids) - 1):
                travel_distance += np.linalg.norm(np.array(centroids[i+1]) - np.array(centroids[i]))
        
        # Calculate metrics
        lengths = [cv2.arcLength(c, _is_contour_closed(c)) for c in ordered_contours]
        total_points = sum(len(c) for c in ordered_contours)
        
        # FIX-13: Curvature-weighted complexity
        curvatures = []
        for c in ordered_contours:
            curvature = _compute_curvature_proxy(c, tracing_config, max_dim)
            curvatures.append(curvature)
        
        # FIX-13: Weighted point count for density estimation
        weighted_points = 0
        for c, curve in zip(ordered_contours, curvatures):
            weight = min(2.0, 1.0 + curve)  # Straight = 1x, curved = up to 2x
            weighted_points += len(c) * weight
        
        return {
            "total_contours": len(ordered_contours),
            "total_points": total_points,
            "weighted_points": weighted_points,
            "total_path_length": sum(lengths),
            "travel_distance": travel_distance,
            "avg_curvature": float(np.mean(curvatures)) if curvatures else 0.0,
            "max_dim": max_dim,
            "adaptive_epsilon": scale_epsilon,
            "ordered_contours": ordered_contours,  # For later use
        }
    except Exception as e:
        logger.debug(f"Contour analysis failed: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# §9  Draw time estimation
# ══════════════════════════════════════════════════════════════════════════════

def _is_binary_like_analysis_image(gray: np.ndarray) -> bool:
    unique_vals = np.unique(gray)
    if len(unique_vals) <= 4:
        return True
    return len(unique_vals) <= 16 and float(gray.std()) > 80.0


def _normalize_analysis_binary(gray: np.ndarray) -> np.ndarray:
    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    if np.count_nonzero(binary) > binary.size * 0.5:
        binary = cv2.bitwise_not(binary)
    return binary

def _estimate_draw_time(
    image_path: Path,
    mode: PipelineMode,
    density: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Enhanced estimation with curvature weighting and ordered travel."""
    density = density or _analyze_contour_density(image_path, mode)
    config = _get_pipeline_config(mode)
    rendering_config = config.rendering
    
    if not density or density["total_contours"] == 0:
        return {"estimated_seconds": 0, "point_count": 0}
    
    # Use weighted points for complexity
    point_count = density.get("weighted_points", density["total_points"])
    contour_count = density["total_contours"]
    travel_distance = density.get("travel_distance", 0)
    curvature = density.get("avg_curvature", 0)
    
    # Base time with curvature weighting (FIX-13)
    base_time = point_count * 0.005 * (1.0 + curvature * 0.5)
    
    # Travel time
    travel_time = travel_distance * 0.0001
    
    # Pen lift time
    pen_lift_time = contour_count * (rendering_config.pen_lift_time_ms / 1000)
    
    # Curvature penalty
    curvature_penalty = curvature * 0.3
    
    estimated_seconds = base_time + travel_time + pen_lift_time + curvature_penalty
    
    # Interpolation overhead
    if config.tracing.interpolate:
        estimated_seconds *= rendering_config.interpolation_overhead
    
    return {
        "estimated_seconds": estimated_seconds,
        "point_count": point_count,
        "contour_count": contour_count,
        "travel_distance": travel_distance,
    }


def _should_draw(estimate: Dict[str, float], mode: PipelineMode) -> bool:
    config = _get_pipeline_config(mode)
    rendering_config = config.rendering

    point_count = float(estimate.get("point_count", 0) or 0)
    contour_count = int(estimate.get("contour_count", 0) or 0)

    if point_count <= 0 or contour_count <= 0:
        logger.warning("Rejected: candidate produced no drawable contours")
        return False
    
    if estimate["estimated_seconds"] > rendering_config.max_draw_time:
        logger.warning(f"Rejected: {estimate['estimated_seconds']:.1f}s > {rendering_config.max_draw_time}s")
        return False
    
    if point_count > rendering_config.max_points:
        logger.warning(f"Rejected: {point_count} points > {rendering_config.max_points}")
        return False
    
    return True


# ══════════════════════════════════════════════════════════════════════════════
# §10  Preprocessing (FIX-9)
# ══════════════════════════════════════════════════════════════════════════════

def _preprocess_image(image_path: Path, mode: PipelineMode) -> Path:
    """Mode‑aware preprocessing with gentler denoise for sketches."""
    config = _get_pipeline_config(mode)
    preprocess_config = config.preprocess
    
    if _is_preprocessed_asset(image_path):
        expected_path = _processed_asset_path(image_path, mode)
        if image_path == expected_path:
            return image_path
        image_path = _get_raw_asset_path(image_path)

    out_path = _processed_asset_path(image_path, mode)
    if out_path.exists():
        return out_path
    
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return image_path

        h, w = img.shape[:2]
        
        # Resize before threshold
        if preprocess_config.resize_before_threshold and min(h, w) < preprocess_config.upscale_min_dim:
            scale_factor = preprocess_config.upscale_min_dim / min(h, w)
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            interpolation = cv2.INTER_CUBIC if scale_factor > 1 else cv2.INTER_AREA
            img = cv2.resize(img, (new_w, new_h), interpolation=interpolation)
            h, w = img.shape[:2]
        
        # FIX-9: Gentler denoise with smaller kernel
        kernel = preprocess_config.denoise_kernel
        if preprocess_config.denoise_type == "median":
            img = cv2.medianBlur(img, kernel)
        elif preprocess_config.denoise_type == "gaussian":
            img = cv2.GaussianBlur(img, (kernel, kernel), 0)
        elif preprocess_config.denoise_type == "bilateral":
            img = cv2.bilateralFilter(img, kernel, 75, 75)
        else:  # nlmeans
            img = cv2.fastNlMeansDenoising(img, h=preprocess_config.denoise_strength)
        
        # CLAHE
        if preprocess_config.apply_clahe:
            clahe = cv2.createCLAHE(clipLimit=preprocess_config.clahe_clip, tileGridSize=(8, 8))
            img = clahe.apply(img)
        
        # Sharpen
        if preprocess_config.sharpen_method == "mild":
            laplacian = cv2.Laplacian(img, cv2.CV_64F)
            img = np.clip(img.astype(np.float64) - 0.3 * laplacian, 0, 255).astype(np.uint8)
        elif preprocess_config.sharpen_method == "aggressive":
            blurred = cv2.GaussianBlur(img.astype(np.float32), (0, 0), sigmaX=2)
            img = np.clip(img.astype(np.float32) * 1.5 - blurred * 0.5, 0, 255).astype(np.uint8)
        
        # Threshold
        if preprocess_config.apply_adaptive_threshold:
            polarity = _detect_threshold_polarity_histogram(img)
            block_size = _dynamic_adaptive_block_size(h, w)
            img = cv2.adaptiveThreshold(
                img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                polarity, block_size, preprocess_config.adaptive_c
            )
        elif preprocess_config.apply_otsu:
            # FIX-19: Correctly unpack the tuple
            img, _ = _try_both_polarities(img, mode)
        else:
            # Default: use best polarity
            img, _ = _try_both_polarities(img, mode)
        
        cv2.imwrite(str(out_path), img)
        return out_path

    except Exception as exc:
        logger.error(f"Pre-processing failed ({exc})")
        return image_path


def _log_candidate_summary(label: str, mode: PipelineMode, density: Dict[str, Any], estimate: Dict[str, float]) -> None:
    logger.info(
        f"{label}: mode={mode.name} "
        f"Contours={density.get('total_contours', 0)}, "
        f"Points={estimate.get('point_count', 0)}, "
        f"Est time={estimate.get('estimated_seconds', 0.0):.1f}s"
    )


def _evaluate_drawable_candidate(
    image_path: Path,
    mode: PipelineMode,
    label: str,
) -> Optional[DrawableCandidate]:
    processed_path = _preprocess_image(image_path, mode)
    trace_source = _get_trace_source_path(processed_path, mode)
    density = _analyze_contour_density(trace_source, mode)
    estimate = _estimate_draw_time(trace_source, mode, density=density)
    _log_candidate_summary(label, mode, density, estimate)

    if not _should_draw(estimate, mode):
        return None

    return DrawableCandidate(
        processed_path=processed_path,
        mode=mode,
        trace_source=trace_source,
        density=density,
        estimate=estimate,
    )


def _is_preferred_candidate_mode(
    candidate_mode: PipelineMode,
    requested_mode: PipelineMode,
) -> bool:
    if requested_mode is PipelineMode.LOGO:
        return candidate_mode is PipelineMode.LOGO
    if requested_mode is PipelineMode.AUTO:
        return candidate_mode in (PipelineMode.AUTO, PipelineMode.SKETCH)
    return candidate_mode is requested_mode


def _candidate_rank(
    candidate: DrawableCandidate,
    requested_mode: PipelineMode,
) -> float:
    mode_rank_map = {
        PipelineMode.SKETCH: {
            PipelineMode.SKETCH: 3.0,
            PipelineMode.AUTO: 2.0,
            PipelineMode.LOGO: 1.0,
        },
        PipelineMode.AUTO: {
            PipelineMode.AUTO: 3.0,
            PipelineMode.SKETCH: 2.5,
            PipelineMode.LOGO: 1.0,
        },
        PipelineMode.LOGO: {
            PipelineMode.LOGO: 3.0,
            PipelineMode.SKETCH: 1.5,
            PipelineMode.AUTO: 1.0,
        },
    }
    mode_rank = mode_rank_map.get(requested_mode, {}).get(candidate.mode, 0.0)
    contour_count = int(candidate.density.get("total_contours", 0) or 0)
    point_count = float(candidate.estimate.get("point_count", 0) or 0)
    est_seconds = float(candidate.estimate.get("estimated_seconds", 0.0) or 0.0)
    detail_bonus = min(contour_count, 24) * 6 + min(point_count, 1200.0) * 0.05
    return mode_rank * 1000.0 + detail_bonus - est_seconds


def _pick_better_candidate(
    current_best: Optional[DrawableCandidate],
    candidate: Optional[DrawableCandidate],
    requested_mode: PipelineMode,
) -> Optional[DrawableCandidate]:
    if candidate is None:
        return current_best
    if current_best is None:
        return candidate
    return (
        candidate
        if _candidate_rank(candidate, requested_mode) > _candidate_rank(current_best, requested_mode)
        else current_best
    )


def _build_outline_fallback(image_path: Path) -> Optional[Path]:
    raw_path = _get_raw_asset_path(image_path)
    outline_path = raw_path.with_stem(f"{raw_path.stem}_outline")
    if outline_path.exists():
        return outline_path

    try:
        gray = cv2.imread(str(raw_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None

        min_dim = min(gray.shape[:2])
        max_dim = max(gray.shape[:2])
        image_area = float(gray.shape[0] * gray.shape[1])
        best_contours: List[np.ndarray] = []
        best_score = -1.0

        blur_sizes = {
            _odd_kernel_size(min_dim / 40, minimum=9),
            _odd_kernel_size(min_dim / 28, minimum=15),
        }
        close_sizes = {
            _odd_kernel_size(min_dim / 40, minimum=11),
            _odd_kernel_size(min_dim / 24, minimum=17),
        }

        def _pick_contours(binary: np.ndarray) -> Tuple[List[np.ndarray], float]:
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            ranked = [
                c for c in contours
                if not _is_border_frame_contour(c, gray.shape[1], gray.shape[0])
            ]
            ranked = [
                c for c in ranked
                if cv2.contourArea(c) >= image_area * OUTLINE_MIN_AREA_RATIO
            ]
            ranked.sort(key=cv2.contourArea, reverse=True)

            if not ranked:
                return [], -1.0

            largest_area = cv2.contourArea(ranked[0])
            kept: List[np.ndarray] = []
            for contour in ranked:
                area = cv2.contourArea(contour)
                if len(kept) >= 2:
                    break
                if area >= largest_area * 0.12 or not kept:
                    kept.append(contour)

            if not kept:
                return [], -1.0

            total_area = sum(cv2.contourArea(c) for c in kept)
            score = total_area - abs(len(kept) - 1) * (image_area * 0.04)
            return kept, score

        for blur_size in sorted(blur_sizes):
            blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
            for close_size in sorted(close_sizes):
                close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
                open_size = _odd_kernel_size(close_size / 3, minimum=5)
                open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size))

                for polarity in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
                    _, binary = cv2.threshold(blurred, 0, 255, polarity | cv2.THRESH_OTSU)
                    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel, iterations=2)
                    merged = cv2.morphologyEx(merged, cv2.MORPH_OPEN, open_kernel, iterations=1)
                    contours, score = _pick_contours(merged)
                    if score > best_score:
                        best_contours = contours
                        best_score = score

        if not best_contours:
            return None

        canvas = np.full(gray.shape, 255, dtype=np.uint8)
        epsilon = max(2.0, max_dim * 0.004)
        thickness = max(2, int(round(max_dim / 220)))

        for contour in best_contours:
            simplified = cv2.approxPolyDP(contour, epsilon=epsilon, closed=True)
            cv2.drawContours(canvas, [simplified], -1, 0, thickness=thickness)

        cv2.imwrite(str(outline_path), canvas)
        logger.info(f"Generated local outline fallback: {outline_path}")
        return outline_path

    except Exception as exc:
        logger.warning(f"Outline fallback generation failed: {exc}")
        return None


def _resolve_drawable_candidate(
    image_path: Path,
    primary_mode: PipelineMode,
    label: str,
) -> Optional[DrawableCandidate]:
    raw_path = _get_raw_asset_path(image_path)
    best_candidate: Optional[DrawableCandidate] = None

    for candidate_mode in _build_attempt_chain(primary_mode):
        candidate = _evaluate_drawable_candidate(raw_path, candidate_mode, label)
        if candidate is not None and _is_preferred_candidate_mode(candidate.mode, primary_mode):
            return candidate
        best_candidate = _pick_better_candidate(best_candidate, candidate, primary_mode)

    outline_path = _build_outline_fallback(raw_path)
    if outline_path is not None:
        logger.info(f"{label}: attempting local outline rescue.")
        for candidate_mode in (PipelineMode.SKETCH, PipelineMode.AUTO, PipelineMode.LOGO):
            candidate = _evaluate_drawable_candidate(
                outline_path,
                candidate_mode,
                f"{label} outline",
            )
            if candidate is not None and _is_preferred_candidate_mode(candidate.mode, primary_mode):
                return candidate
            best_candidate = _pick_better_candidate(best_candidate, candidate, primary_mode)

    return best_candidate


# ══════════════════════════════════════════════════════════════════════════════
# §11  Image generation
# ══════════════════════════════════════════════════════════════════════════════

def _generate_prompt(query: str, mode: PipelineMode) -> str:
    base = query.strip()
    _trace_friendly = (
        "black and white only, bold clean contour lines, plain white background, "
        "one subject only, centered composition, full subject visible, isolated subject, "
        "no text, no watermark, no decorative border, no repeated body parts, "
        "no extra heads, no shading, no texture, no crosshatching, no grayscale fills"
    )
    
    if mode is PipelineMode.SKETCH:
        return (
            f"Simple children's coloring-book outline of {base}, clear outer silhouette, "
            f"very few interior guide lines, easy to trace, simple pose, {_trace_friendly}"
        )
    if mode is PipelineMode.LOGO:
        return (
            f"Minimal flat icon of {base}, bold silhouette, simple clean shapes, "
            f"strong negative space, {_trace_friendly}"
        )
    return (
        f"Simple outline illustration of {base}, recognizable silhouette, "
        f"minimal interior lines, easy to trace, {_trace_friendly}"
    )


def _request_remote_image(url: str, headers: Dict[str, str]) -> Optional[requests.Response]:
    """Fetch a generated image with a hard wall-clock deadline."""
    response_holder: List[Optional[requests.Response]] = [None]
    error_holder: List[Optional[Exception]] = [None]

    def _worker() -> None:
        try:
            response_holder[0] = requests.get(
                url,
                headers=headers,
                timeout=(REMOTE_IMAGE_CONNECT_TIMEOUT_S, REMOTE_IMAGE_READ_TIMEOUT_S),
            )
        except Exception as exc:
            error_holder[0] = exc

    thread = threading.Thread(
        target=_worker,
        daemon=True,
        name="BotbroImageFetch",
    )
    thread.start()
    thread.join(timeout=REMOTE_IMAGE_DEADLINE_S)

    if thread.is_alive():
        logger.warning(
            f"Remote image request exceeded {REMOTE_IMAGE_DEADLINE_S:.0f}s deadline."
        )
        return None

    if error_holder[0] is not None:
        raise error_holder[0]

    return response_holder[0]


def _download_image(query: str, mode: PipelineMode) -> Optional[DrawableCandidate]:
    config = _get_pipeline_config(mode)
    prompt = _generate_prompt(query, mode)
    encoded = urllib.parse.quote(prompt)
    headers = {"User-Agent": "Botbro-AI-Assistant/1.0"}
    safe_name = _safe_filename(query)

    for attempt in range(1, REMOTE_IMAGE_ATTEMPTS + 1):
        logger.info(
            f"Generating image (attempt {attempt}/{REMOTE_IMAGE_ATTEMPTS}) for "
            f"'{query}' mode={mode.name}"
        )
        seed = attempt * 997
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=600&height=600&nologo=true&seed={seed}"
        
        try:
            logger.info(f"Attempt {attempt}: requesting remote asset.")
            resp = _request_remote_image(url, headers)
            if resp is None:
                time.sleep(REMOTE_IMAGE_RETRY_DELAY_S)
                continue

            if resp.status_code != 200:
                logger.warning(f"Attempt {attempt}: remote service returned HTTP {resp.status_code}")
                time.sleep(REMOTE_IMAGE_RETRY_DELAY_S)
                continue

            if not resp.content:
                logger.warning(f"Attempt {attempt}: remote service returned an empty image payload")
                time.sleep(REMOTE_IMAGE_RETRY_DELAY_S)
                continue

            raw_path = _versioned_asset_path(safe_name, mode, prompt, config)
            raw_path.write_bytes(resp.content)
            logger.info(f"Attempt {attempt}: saved remote asset to {raw_path}")

            if not _is_image_quality_good(raw_path, mode):
                logger.warning(f"Attempt {attempt}: quality gate failed")
                raw_path.unlink(missing_ok=True)
                time.sleep(REMOTE_IMAGE_RETRY_DELAY_S)
                continue

            logger.info(f"Attempt {attempt}: evaluating downloaded asset.")
            candidate = _resolve_drawable_candidate(
                raw_path,
                mode,
                f"Attempt {attempt}",
            )
            if candidate is not None:
                return candidate

        except Exception as exc:
            logger.error(f"Attempt {attempt} download pipeline failed: {exc}")
            time.sleep(REMOTE_IMAGE_RETRY_DELAY_S)
            continue

    return None


def _trace_image(image_path: Path, mode: PipelineMode) -> bool:
    config = _get_pipeline_config(mode)
    
    try:
        ok = ImageTracer.trace_image(
            str(image_path),
            start_x=0,
            start_y=0,
            scale=config.trace_scale,
            mode=mode,
        )
        return bool(ok)
    except Exception as exc:
        logger.error(f"Tracing error: {exc}")
        return False


def _click_canvas_center() -> Tuple[int, int]:
    sw, sh = pyautogui.size()
    cx, cy = sw // 2, sh // 2
    pyautogui.click(cx, cy)
    time.sleep(0.5)
    return cx, cy


# ══════════════════════════════════════════════════════════════════════════════
# §13  Placeholder rendering (FIX-18)
# ══════════════════════════════════════════════════════════════════════════════

def _render_placeholder(cx: int, cy: int, points):
    if not points:
        return

    pyautogui.moveTo(points[0][0], points[0][1])

    if len(points) == 1:
        pyautogui.click()
        return

    for x, y in points[1:]:
        pyautogui.dragTo(x, y, duration=0.02, button="left")


def _draw_geometric_placeholder(cx: int, cy: int, mode: PipelineMode) -> None:
    """Mode‑aware placeholder using unified renderer."""
    if mode == PipelineMode.SKETCH:
        # Paw print
        points = []
        r = 60
        for i in range(36):
            angle = 2 * math.pi * i / 36
            points.append((cx + int(r * 0.6 * math.cos(angle)), cy + int(r * 0.6 * math.sin(angle))))
        _render_placeholder(cx, cy - r, points)
        
        for tx, ty in [(cx-50, cy-80), (cx, cy-90), (cx+50, cy-80)]:
            toe_points = []
            for i in range(12):
                angle = 2 * math.pi * i / 12
                toe_points.append((tx + int(15 * math.cos(angle)), ty + int(15 * math.sin(angle))))
            _render_placeholder(tx, ty, toe_points)
    
    elif mode == PipelineMode.LOGO:
        # Shield
        points = [
            (cx, cy - 70), (cx + 50, cy - 70), (cx + 50, cy - 20),
            (cx, cy + 60), (cx - 50, cy - 20), (cx - 50, cy - 70), (cx, cy - 70)
        ]
        _render_placeholder(cx, cy, points)
    
    else:
        # Circle + cross
        points = []
        r = 80
        for i in range(37):
            angle = 2 * math.pi * i / 36
            points.append((cx + int(r * math.cos(angle)), cy + int(r * math.sin(angle))))
        _render_placeholder(cx + r, cy, points)
        
        cross_points = [(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r)]
        for x, y in cross_points:
            _render_placeholder(x, y, [(x, y)])


def _draw_spiral(cx: int, cy: int) -> None:
    """Last‑resort spiral fallback."""
    points = []
    for t in np.linspace(0, 12 * math.pi, 400):
        r = 4 * t
        x = cx + int(r * math.cos(t))
        y = cy + int(r * math.sin(t))
        points.append((x, y))
    _render_placeholder(cx, cy, points)


# ══════════════════════════════════════════════════════════════════════════════
# §14  Public API
# ══════════════════════════════════════════════════════════════════════════════

def draw_from_local_image(image_path_str: str) -> str:
    """
    Convert a user-supplied colour image to a sketch and draw it in MS Paint.

    Pipeline:
      1. Read image (colour or grayscale).
      2. Convert to greyscale if needed.
      3. Upscale if too small.
      4. CLAHE contrast enhancement.
      5. Adaptive threshold → pencil-sketch binary mask.
      6. Save to assets/ as a temporary PNG.
      7. Evaluate & trace using the existing SKETCH pipeline.
    """
    image_path = Path(image_path_str).resolve()
    if not image_path.exists():
        return f"❌ Image file not found: {image_path}"

    logger.info(f"[DrawFromLocal] Converting '{image_path.name}' to sketch …")

    # ── 1. Load image ────────────────────────────────────────────────────────
    raw = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return f"❌ Could not read image: {image_path}"

    # ── 2. Convert to greyscale ───────────────────────────────────────────────
    if raw.ndim == 2:
        gray = raw
    elif raw.shape[2] == 4:
        gray = cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY)
    else:
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)

    # ── 3. Upscale small images ───────────────────────────────────────────────
    h, w = gray.shape[:2]
    target_min_dim = 900
    if min(h, w) < target_min_dim:
        scale_up = target_min_dim / min(h, w)
        gray = cv2.resize(
            gray,
            (int(w * scale_up), int(h * scale_up)),
            interpolation=cv2.INTER_CUBIC,
        )
        h, w = gray.shape[:2]
        logger.debug(f"[DrawFromLocal] Upscaled to {w}×{h}")

    # ── 4. CLAHE contrast enhancement ────────────────────────────────────────
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # ── 5. Adaptive threshold → binary sketch mask ───────────────────────────
    block_size = max(11, (_odd_kernel_size(min(h, w) // 40, minimum=11)))
    sketch_bin = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,   # dark strokes on white background
        block_size,
        4,
    )
    # Clean up salt-and-pepper noise
    sketch_bin = cv2.medianBlur(sketch_bin, 3)

    # ── 6. Save sketch PNG to assets/ ────────────────────────────────────────
    safe_stem = _safe_filename(image_path.stem)
    sketch_path = ASSETS_DIR / f"_user_upload_{safe_stem}_sketch.png"
    cv2.imwrite(str(sketch_path), sketch_bin)
    logger.info(f"[DrawFromLocal] Sketch saved → {sketch_path}")

    # ── 7. Evaluate & trace using SKETCH pipeline ─────────────────────────────
    mode = PipelineMode.SKETCH
    _click_canvas_center()

    candidate = _resolve_drawable_candidate(sketch_path, mode, "UserUpload")
    if candidate is None:
        # Try AUTO fallback
        logger.warning("[DrawFromLocal] SKETCH candidate rejected — trying AUTO.")
        candidate = _resolve_drawable_candidate(sketch_path, PipelineMode.AUTO, "UserUpload-AUTO")

    if candidate is None:
        cx, cy = _click_canvas_center()
        _draw_geometric_placeholder(cx, cy, mode)
        return "I had trouble extracting the details from your image, so I drew a simple sketch in Paint instead. Try a clearer photo for better results! 🎨"

    if not _trace_image(candidate.trace_source, candidate.mode):
        return "I converted your image to a sketch but ran into an issue while drawing it in Paint. Please make sure Paint is open and try again."

    logger.info("[DrawFromLocal] Drawing completed successfully.")
    return f"Done! ✅ I converted your image to a sketch and drew it in Paint. It looks great! 🎨"


def draw_anything(shape_name: str) -> str:
    """Master drawing function with complete orchestration pipeline."""
    primary_mode = _detect_best_mode(shape_name)
    logger.info(f"[DrawEngine] shape='{shape_name}' primary_mode={primary_mode.name}")

    _manage_cache_size()
    _click_canvas_center()

    attempt_chain = _build_attempt_chain(primary_mode)
    logger.info(f"Attempt chain: {[m.name for m in attempt_chain]}")

    for mode in attempt_chain:
        logger.info(f"-- Pipeline attempt: mode={mode.name} --")
        
        config = _get_pipeline_config(mode)
        prompt = _generate_prompt(shape_name, mode)
        cached_path = _versioned_asset_path(_safe_filename(shape_name), mode, prompt, config)
        local_asset = _find_local_asset(shape_name, mode)
        candidate: Optional[DrawableCandidate] = None

        if local_asset is not None:
            logger.info(f"Using local asset: {local_asset}")
            candidate = _resolve_drawable_candidate(
                local_asset,
                mode,
                "Local asset",
            )
        elif cached_path.exists():
            logger.info(f"Using cached asset: {cached_path}")
            candidate = _resolve_drawable_candidate(
                cached_path,
                mode,
                "Cached asset",
            )
        else:
            candidate = _download_image(shape_name, mode)
            if candidate is None:
                logger.warning(f"Generation failed for mode {mode.name}")
                continue

        if candidate is None:
            logger.warning(f"No drawable candidate available for mode {mode.name}")
            continue

        if not _trace_image(candidate.trace_source, candidate.mode):
            logger.warning(f"Tracing failed for {candidate.processed_path}")
            continue

        logger.info(f"Drawing completed successfully with mode {candidate.mode.name}")
        return f"Done! ✅ I drew '{shape_name}' in Paint for you. Take a look! 🎨"

    logger.warning(f"All modes failed, drawing placeholder")
    cx, cy = _click_canvas_center()
    _draw_geometric_placeholder(cx, cy, primary_mode)
    return f"I couldn't find a great reference image for '{shape_name}', so I drew a symbolic shape in Paint instead. Try a more specific subject for best results! 🖼️"
