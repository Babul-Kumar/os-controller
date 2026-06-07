import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Keys
# Removed Gemini API Key, using local Ollama model

# App Configuration
APP_NAME = "Botbro AI Assistant"
VERSION = "1.0.1"

# Voice Configuration
VOICE_RATE = 175 # Speech rate (words per minute)
VOICE_VOLUME = 1.0 # Volume level (0.0 to 1.0)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "memory.db")

# Safety Configuration
REQUIRE_CONFIRMATION = True # If True, dangerous commands require user confirmation

# ── Speech-To-Text Configuration ─────────────────────────────────────────────
# Model: distil-small.en is the default — fast, accurate, command-oriented.
# Other options: "base.en", "small.en", "medium.en", "large-v3"
STT_MODEL = os.environ.get("STT_MODEL", "distil-small.en")

# Device override. Leave empty ("") for automatic GPU/CPU detection.
# Set to "cpu" to force CPU regardless of GPU availability.
# Set to "cuda" to force GPU (requires NVIDIA GPU + CUDA toolkit).
STT_DEVICE = os.environ.get("STT_DEVICE", "")

# Compute type override. Leave empty ("") for automatic selection.
# CPU:  "int8" (fastest), "float32" (highest quality)
# GPU:  "float16" (fastest), "bfloat16", "float32"
STT_COMPUTE = os.environ.get("STT_COMPUTE", "")

# Force transcription language — improves speed by skipping language detection.
STT_LANGUAGE = os.environ.get("STT_LANGUAGE", "en")

# Beam search width (higher = more accurate but slower).
STT_BEAM_SIZE = int(os.environ.get("STT_BEAM_SIZE", "5"))
