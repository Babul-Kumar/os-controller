"""
FileFinder — gives Botbro the ability to search the entire PC for files.
Searches by name, extension, or keyword.
"""
import os
import glob
import fnmatch
from typing import List, Optional
from utils.helpers import setup_logger

logger = setup_logger(__name__)


class FileFinder:
    # Default search roots — Desktop, Documents, Downloads, and entire C:\ (slower)
    DEFAULT_ROOTS = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Pictures"),
        os.path.expanduser("~/Music"),
        os.path.expanduser("~/Videos"),
    ]

    @staticmethod
    def find_by_name(filename: str, roots: Optional[List[str]] = None,
                     max_results: int = 10) -> List[str]:
        """
        Search for a file by name (supports wildcards like *.mp3).
        Returns a list of matching file paths.
        """
        roots = roots or FileFinder.DEFAULT_ROOTS
        results = []

        for root in roots:
            if not os.path.exists(root):
                continue
            for dirpath, _, files in os.walk(root):
                for f in files:
                    if fnmatch.fnmatch(f.lower(), filename.lower()):
                        results.append(os.path.join(dirpath, f))
                        if len(results) >= max_results:
                            return results
        return results

    @staticmethod
    def find_image_for(query: str, roots: Optional[List[str]] = None) -> Optional[str]:
        """
        Search the PC for an image that matches the given query string.
        Returns the path of the first match, or None.
        """
        image_exts = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.gif", "*.webp"]
        roots = roots or FileFinder.DEFAULT_ROOTS

        # Try exact name matches first
        for ext in image_exts:
            pattern = f"*{query.replace(' ', '*')}*"
            results = FileFinder.find_by_name(f"{pattern}", roots=roots, max_results=1)
            if results:
                logger.info(f"Found image on PC: {results[0]}")
                return results[0]

        logger.info(f"No matching image found for '{query}' on the PC.")
        return None

    @staticmethod
    def find_by_extension(ext: str, roots: Optional[List[str]] = None,
                          max_results: int = 20) -> List[str]:
        """Find all files with a given extension (e.g. 'mp3', 'pdf')."""
        ext = ext.lstrip(".")
        return FileFinder.find_by_name(f"*.{ext}", roots=roots, max_results=max_results)

    @staticmethod
    def search_deep(query: str, max_results: int = 10) -> List[str]:
        """
        Deep search across the entire C: drive. Slower but thorough.
        """
        deep_roots = ["C:\\"]
        return FileFinder.find_by_name(query, roots=deep_roots, max_results=max_results)
