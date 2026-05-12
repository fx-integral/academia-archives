"""
Auto Updater Module
Handles automatic version checking and updating from GitHub releases
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.request import Request, urlopen

from loguru import logger


class AutoUpdater:
    """Auto updater for ByteLeap Miner/Worker"""

    GITHUB_REPO = "byteleapai/byteleap-Miner"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    CHECK_INTERVAL = 3600  # Check every hour (3600 seconds)

    def __init__(self, current_version: str, project_root: Path):
        """
        Initialize auto updater

        Args:
            current_version: Current version string (e.g., "0.0.4")
            project_root: Project root directory path
        """
        self.current_version = current_version
        self.project_root = project_root
        self._check_task = None
        self._should_stop = False

    def _normalize_version(self, version: str) -> str:
        """
        Normalize version string by removing prefixes like 'v', 'release-v', etc.

        Args:
            version: Version string (e.g., "v0.0.5", "release-v0.0.5", "0.0.5")

        Returns:
            Normalized version string (e.g., "0.0.5")
        """
        # Remove common prefixes
        version = version.strip()
        if version.startswith("release-v"):
            version = version[9:]  # Remove "release-v"
        elif version.startswith("release-"):
            version = version[8:]  # Remove "release-"
        elif version.startswith("v"):
            version = version[1:]  # Remove "v"
        return version

    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two version strings

        Args:
            version1: First version string (e.g., "0.0.4")
            version2: Second version string (e.g., "0.0.5")

        Returns:
            -1 if version1 < version2
            0 if version1 == version2
            1 if version1 > version2
        """
        # Normalize versions by removing prefixes
        v1_parts = self._normalize_version(version1).split(".")
        v2_parts = self._normalize_version(version2).split(".")

        # Pad to same length
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts += ["0"] * (max_len - len(v1_parts))
        v2_parts += ["0"] * (max_len - len(v2_parts))

        # Compare each part
        for p1, p2 in zip(v1_parts, v2_parts):
            try:
                n1, n2 = int(p1), int(p2)
                if n1 < n2:
                    return -1
                elif n1 > n2:
                    return 1
            except ValueError:
                # String comparison for non-numeric parts
                if p1 < p2:
                    return -1
                elif p1 > p2:
                    return 1

        return 0

    async def check_for_updates(self) -> Optional[Dict]:
        """
        Check for available updates from GitHub releases

        Returns:
            Dictionary with update info if available, None otherwise
            {
                "version": "0.0.5",
                "download_url": "https://...",
                "changelog": "..."
            }
        """
        try:
            # Create request with user agent
            req = Request(
                self.GITHUB_API_URL, headers={"User-Agent": "ByteLeap-AutoUpdater"}
            )

            # Fetch latest release info
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            tag_name = data.get("tag_name", "")
            if not tag_name:
                logger.warning("Failed to get latest version info")
                return None

            # Normalize version from tag_name (e.g., "release-v0.0.5" -> "0.0.5")
            latest_version = self._normalize_version(tag_name)
            if not latest_version:
                logger.warning("Failed to normalize version from tag_name")
                return None

            # Compare versions
            if self._compare_versions(self.current_version, latest_version) >= 0:
                logger.debug(f"Current version {self.current_version} is already the latest")
                return None

            # Get download URL for source code zip
            download_url = data.get("zipball_url")
            if not download_url:
                logger.warning("Failed to get download URL")
                return None

            return {
                "version": latest_version,
                "download_url": download_url,
                "changelog": data.get("body", ""),
                "release_url": data.get("html_url", ""),
            }

        except Exception as e:
            logger.error(f"Failed to check for updates: {e}")
            return None

    def _download_file(self, url: str, dest_path: Path) -> bool:
        """
        Download file from URL

        Args:
            url: Download URL
            dest_path: Destination file path

        Returns:
            True if successful, False otherwise
        """
        try:
            req = Request(url, headers={"User-Agent": "ByteLeap-AutoUpdater"})

            with urlopen(req, timeout=30) as response:
                with open(dest_path, "wb") as f:
                    # Download in chunks
                    chunk_size = 8192
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)

            logger.info(f"Download completed: {dest_path}")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def _extract_zip(self, zip_path: Path, extract_to: Path) -> Optional[Path]:
        """
        Extract ZIP file

        Args:
            zip_path: Path to ZIP file
            extract_to: Directory to extract to

        Returns:
            Path to extracted directory, or None if failed
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_to)

            # Find the extracted directory (GitHub zips extract to a subdirectory)
            extracted_dirs = [
                d for d in extract_to.iterdir() if d.is_dir() and d.name.startswith("byteleapai-")
            ]

            if not extracted_dirs:
                logger.error("Extracted directory not found")
                return None

            return extracted_dirs[0]

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return None

    def _count_file_lines(self, file_path: Path) -> int:
        """
        Count lines in a file

        Args:
            file_path: Path to file

        Returns:
            Number of lines in file, 0 if file doesn't exist or error
        """
        try:
            if not file_path.exists():
                return 0
            with open(file_path, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception as e:
            logger.warning(f"Failed to count lines in {file_path}: {e}")
            return 0

    def _compare_config_files_by_lines(
        self, old_config_dir: Path, new_config_dir: Path
    ) -> Dict[str, Any]:
        """
        Compare configuration files by line count between old and new versions

        Args:
            old_config_dir: Old config directory
            new_config_dir: New config directory

        Returns:
            Dictionary with:
            - "added": list of added config files
            - "removed": list of removed config files
            - "same_line_count": list of files with same line count (use old)
            - "different_line_count": list of files with different line count (use new)
        """
        old_configs = {f.name: f for f in old_config_dir.glob("*.yaml")}
        new_configs = {f.name: f for f in new_config_dir.glob("*.yaml")}

        added = set(new_configs.keys()) - set(old_configs.keys())
        removed = set(old_configs.keys()) - set(new_configs.keys())
        common = set(old_configs.keys()) & set(new_configs.keys())

        same_line_count = []
        different_line_count = []

        # Compare line counts for common files
        for config_name in common:
            try:
                old_lines = self._count_file_lines(old_configs[config_name])
                new_lines = self._count_file_lines(new_configs[config_name])

                if old_lines == new_lines:
                    same_line_count.append(config_name)
                else:
                    different_line_count.append(
                        {
                            "file": config_name,
                            "old_lines": old_lines,
                            "new_lines": new_lines,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to compare config file {config_name}: {e}")
                # On error, treat as different to be safe
                different_line_count.append({"file": config_name, "old_lines": 0, "new_lines": 0})

        return {
            "added": list(added),
            "removed": list(removed),
            "same_line_count": same_line_count,
            "different_line_count": different_line_count,
        }

    def _flatten_dict_keys(self, d: dict, parent_key: str = "") -> list:
        """
        Flatten nested dictionary keys

        Args:
            d: Dictionary to flatten
            parent_key: Parent key prefix

        Returns:
            List of flattened keys
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict_keys(v, new_key))
            else:
                items.append(new_key)
        return items

    async def download_and_install_update(self, update_info: Dict) -> bool:
        """
        Download and install update atomically

        Args:
            update_info: Update information from check_for_updates

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Downloading new version {update_info['version']}...")

        # Directories to exclude from update
        EXCLUDE_DIRS = {"config", "__pycache__", ".git", "logs", "config_backup", ".venv", "venv"}

        # Create temporary directory for staging the update
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "update.zip"
            staging_dir = temp_path / "staging"

            try:
                # Download update
                if not self._download_file(update_info["download_url"], zip_path):
                    return False

                # Extract update
                extracted_dir = self._extract_zip(zip_path, temp_path)
                if not extracted_dir:
                    return False

                logger.info(f"Extraction completed: {extracted_dir}")

                # Create staging directory
                staging_dir.mkdir(exist_ok=True)

                # Compare config files by line count
                old_config_dir = self.project_root / "config"
                new_config_dir = extracted_dir / "config"
                config_diff = None

                if old_config_dir.exists() and new_config_dir.exists():
                    config_diff = self._compare_config_files_by_lines(old_config_dir, new_config_dir)

                    # Log config comparison results
                    if config_diff["added"] or config_diff["removed"] or config_diff["different_line_count"]:
                        logger.warning("=" * 60)
                        logger.warning("Configuration files analysis:")
                        logger.warning("=" * 60)

                        if config_diff["added"]:
                            logger.info(f"New config files (will be added): {', '.join(config_diff['added'])}")

                        if config_diff["removed"]:
                            logger.warning(f"Removed config files: {', '.join(config_diff['removed'])}")

                        if config_diff["same_line_count"]:
                            logger.info(
                                f"Config files with same line count (will keep old): {', '.join(config_diff['same_line_count'])}"
                            )

                        if config_diff["different_line_count"]:
                            logger.warning("Config files with different line count (will use new):")
                            for diff in config_diff["different_line_count"]:
                                logger.warning(
                                    f"  {diff['file']}: old={diff['old_lines']} lines, new={diff['new_lines']} lines"
                                )

                        logger.warning("=" * 60)

                # Backup current config
                backup_dir = self.project_root / "config_backup"
                if old_config_dir.exists():
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir)
                    shutil.copytree(old_config_dir, backup_dir)
                    logger.info(f"Config backed up to: {backup_dir}")

                # Stage all files from extracted directory (excluding excluded dirs)
                logger.info("Preparing update files...")
                for item in extracted_dir.iterdir():
                    if item.name in EXCLUDE_DIRS:
                        continue

                    staging_item = staging_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, staging_item)
                    else:
                        shutil.copy2(item, staging_item)

                # Handle config directory: use old config if line count matches
                if old_config_dir.exists() and new_config_dir.exists() and config_diff:
                    staging_config_dir = staging_dir / "config"
                    staging_config_dir.mkdir(exist_ok=True)

                    # Copy all config files from new version first
                    for config_file in new_config_dir.glob("*.yaml"):
                        shutil.copy2(config_file, staging_config_dir / config_file.name)

                    # Replace with old config files if line count matches
                    for config_name in config_diff["same_line_count"]:
                        old_config_file = old_config_dir / config_name
                        staging_config_file = staging_config_dir / config_name
                        if old_config_file.exists():
                            shutil.copy2(old_config_file, staging_config_file)
                            logger.info(f"Keeping old config file (same line count): {config_name}")

                    # New config files (added) are already copied from new version above
                    # Files with different line count are already copied from new version above
                    # Removed config files are not copied (they don't exist in new version)

                elif new_config_dir.exists():
                    # If old config doesn't exist, just copy new config
                    staging_config_dir = staging_dir / "config"
                    shutil.copytree(new_config_dir, staging_config_dir)
                elif old_config_dir.exists():
                    # If new config doesn't exist but old does, keep old config
                    staging_config_dir = staging_dir / "config"
                    shutil.copytree(old_config_dir, staging_config_dir)
                    logger.info("No new config directory found, keeping old config")

                # Atomically apply update: copy staged files to project root
                logger.info("Applying update atomically...")
                update_errors = []

                for item in staging_dir.iterdir():
                    dest = self.project_root / item.name
                    try:
                        if dest.exists():
                            if dest.is_dir():
                                shutil.rmtree(dest)
                            else:
                                dest.unlink()

                        if item.is_dir():
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)
                    except Exception as e:
                        error_msg = f"Failed to update {item.name}: {e}"
                        logger.error(error_msg)
                        update_errors.append(error_msg)

                if update_errors:
                    logger.error(f"Update completed with {len(update_errors)} errors:")
                    for error in update_errors:
                        logger.error(f"  - {error}")
                    return False

                logger.success(f"Update completed! New version: {update_info['version']}")
                logger.info(f"Release notes: {update_info['release_url']}")

                return True

            except Exception as e:
                logger.error(f"Update failed: {e}", exc_info=True)
                return False

    def restart_process(self, script_args: list):
        """
        Restart current process with new code

        Args:
            script_args: Arguments to pass to new process
        """
        logger.info("Starting new process...")

        # Get current Python executable and script
        python_exe = sys.executable
        script_path = sys.argv[0]

        # Start new process
        subprocess.Popen(
            [python_exe, script_path] + script_args,
            cwd=str(self.project_root),
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        logger.info("New process started, current process will exit...")

    async def check_update_on_startup(self, auto_install: bool = True) -> bool:
        """
        Check for updates on startup

        Args:
            auto_install: Whether to automatically install updates

        Returns:
            True if update was installed, False otherwise
        """
        logger.info(f"Checking for updates... Current version: {self.current_version}")

        update_info = await self.check_for_updates()

        if not update_info:
            logger.info("Already running the latest version")
            return False

        logger.warning("=" * 60)
        logger.warning(f"New version available: {update_info['version']}")
        logger.warning(f"Current version: {self.current_version}")
        logger.warning(f"Release notes: {update_info['release_url']}")
        logger.warning("=" * 60)

        if auto_install:
            success = await self.download_and_install_update(update_info)
            if success:
                logger.warning("Update completed, please check config and restart")
                return True
            else:
                logger.error("Update failed, continuing with current version")

        return False

    async def start_periodic_check(self):
        """Start periodic update checking (every hour)"""
        self._should_stop = False
        logger.info(f"Starting periodic update check (every {self.CHECK_INTERVAL} seconds)")

        while not self._should_stop:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL)

                if self._should_stop:
                    break

                update_info = await self.check_for_updates()

                if update_info:
                    logger.warning("=" * 60)
                    logger.warning(f"New version available: {update_info['version']}")
                    logger.warning(f"Current version: {self.current_version}")
                    logger.warning(f"Release notes: {update_info['release_url']}")
                    logger.warning("Please update when convenient")
                    logger.warning("=" * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic update check failed: {e}")

    def stop_periodic_check(self):
        """Stop periodic update checking"""
        self._should_stop = True
        logger.info("Stopping periodic update check")
