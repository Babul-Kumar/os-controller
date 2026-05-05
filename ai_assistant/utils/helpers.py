import logging
import os
import sys
import json
from datetime import datetime
from rapidfuzz import process

def fuzzy_match(query, choices):
    """Fuzzy match (best match) using rapidfuzz."""
    try:
        result = process.extractOne(query, choices)
        return result[0] if result else None
    except Exception as e:
        logging.getLogger(__name__).error(f"Fuzzy match error: {e}")
        return None

def get_close_suggestions(query, choices, limit=3):
    """Suggest close matches using rapidfuzz."""
    try:
        results = process.extract(query, choices, limit=limit)
        return [r[0] for r in results]
    except Exception as e:
        logging.getLogger(__name__).error(f"Suggestion error: {e}")
        return []

# Setup logs directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        
        # Include any extra kwargs passed via the 'extra' dict
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)
            
        return json.dumps(log_entry, ensure_ascii=False)

def setup_logger(name):
    """Set up a logger with structured JSON formatting."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Console handler (standard formatting for readability in terminal)
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # File handler (JSON formatting)
        app_log_path = os.path.join(LOG_DIR, "app.log")
        file_handler = logging.FileHandler(app_log_path, encoding='utf-8')
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
        
        # Error handler (JSON formatting)
        error_log_path = os.path.join(LOG_DIR, "errors.log")
        error_handler = logging.FileHandler(error_log_path, encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        logger.addHandler(error_handler)
        
    return logger

def json_log(logger, action: str, level=logging.INFO, **payload):
    """Helper to log structured JSON actions."""
    extra = {"extra_data": {"action": action, **payload}}
    logger.log(level, f"Action: {action}", extra=extra)

def ensure_directory(path):
    """Ensure a directory exists, create if not."""
    if not os.path.exists(path):
        os.makedirs(path)

def safe_filename(filename):
    """Return a safe version of a string to be used as a filename."""
    return "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
