import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# App Configuration
APP_NAME = "Botbro AI Assistant"
VERSION = "1.0.0"

# Voice Configuration
VOICE_RATE = 175 # Speech rate (words per minute)
VOICE_VOLUME = 1.0 # Volume level (0.0 to 1.0)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "memory.db")

# Safety Configuration
REQUIRE_CONFIRMATION = True # If True, dangerous commands require user confirmation
