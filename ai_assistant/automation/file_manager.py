import os
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class FileManager:
    @staticmethod
    def create_file(path: str, content: str = "") -> str:
        """Create a new file with optional content."""
        try:
            # Create directories if they don't exist
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
                
            with open(path, 'w', encoding='utf-8') as f:
                if content:
                    f.write(content)
            return f"File '{path}' created successfully."
        except Exception as e:
            logger.error(f"Failed to create file {path}: {e}")
            return f"Failed to create file: {str(e)}"

    @staticmethod
    def delete_file(path: str) -> str:
        """Delete a file."""
        try:
            if os.path.exists(path):
                if os.path.isfile(path):
                    os.remove(path)
                    return f"File '{path}' deleted successfully."
                else:
                    return f"'{path}' is a directory. I can only delete files for safety."
            else:
                return f"File '{path}' not found."
        except Exception as e:
            logger.error(f"Failed to delete file {path}: {e}")
            return f"Failed to delete file: {str(e)}"

    @staticmethod
    def search_file(filename: str, search_path: str = ".") -> str:
        """Search for a file in a given directory (recursive)."""
        # Limiting search to current directory by default for safety/speed
        found_paths = []
        try:
            for root, dirs, files in os.walk(search_path):
                if filename.lower() in [f.lower() for f in files]:
                    # Find exact match
                    for f in files:
                        if f.lower() == filename.lower():
                            found_paths.append(os.path.join(root, f))
            
            if found_paths:
                paths_str = "\n".join(found_paths[:5])
                if len(found_paths) > 5:
                    paths_str += f"\n... and {len(found_paths) - 5} more."
                return f"Found {filename} at:\n{paths_str}"
            else:
                return f"Could not find file '{filename}' in {search_path}"
                
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"Error searching for file: {str(e)}"
