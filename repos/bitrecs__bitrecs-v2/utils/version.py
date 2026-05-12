import os
import logging

logger = logging.getLogger(__name__)


def load_version_info() -> str:
    try:
        version_file_path = os.path.join(os.path.dirname(__file__), '..', 'version.txt')
        if os.path.exists(version_file_path):
            with open(version_file_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                if len(lines) >= 2:
                    branch = lines[0].strip()
                    commit_sha = lines[1].strip()
                    return f"Branch: {branch}, Commit: {commit_sha}"
        return "Version info not available"
    except Exception as e:
        logger.error(f"Error loading version info: {e}")
        return "Error loading version info"