"""
Automatic yt-dlp updater.
Checks PyPI for new yt-dlp releases at startup and periodically in the background,
upgrading the package automatically when a newer version is available.
"""

import importlib.metadata
import logging
import os
import subprocess
import sys
import threading
import time
import requests

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
_update_lock = threading.Lock()


def get_installed_version() -> str:
    """Return the currently installed yt-dlp version string."""
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def get_latest_pypi_version(timeout: int = 5) -> str | None:
    """Fetch the latest yt-dlp version from PyPI, or None on network failure."""
    try:
        resp = requests.get(PYPI_URL, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("info", {}).get("version")
    except Exception as e:
        logger.debug(f"Could not check PyPI for yt-dlp updates: {e}")
        return None


def _parse_version(ver: str) -> tuple[int, ...]:
    """Parse dot-separated version string into a comparable tuple of ints."""
    parts = []
    for part in ver.strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def update_ytdlp_if_needed() -> bool:
    """
    Check PyPI and upgrade yt-dlp if a newer version is available.
    Returns True if an upgrade was performed, False otherwise.
    """
    if os.environ.get("YTDLP_AUTO_UPDATE", "true").lower() in ("0", "false", "no"):
        return False

    with _update_lock:
        current = get_installed_version()
        latest = get_latest_pypi_version()
        if not latest:
            return False

        if _parse_version(latest) <= _parse_version(current):
            logger.info(f"yt-dlp is up to date (v{current}).")
            return False

        logger.info(f"New yt-dlp version available: {current} -> {latest}. Upgrading...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info(f"yt-dlp successfully upgraded to v{latest}.")
                return True
            logger.warning(f"yt-dlp upgrade failed (exit {result.returncode}): {result.stderr.strip()}")
        except Exception as e:
            logger.warning(f"yt-dlp upgrade error: {e}")
        return False


def start_background_updater() -> None:
    """Start a daemon thread that periodically checks for yt-dlp updates."""
    if os.environ.get("YTDLP_AUTO_UPDATE", "true").lower() in ("0", "false", "no"):
        return

    try:
        interval_hours = float(os.environ.get("YTDLP_UPDATE_INTERVAL_HOURS", "12"))
    except ValueError:
        interval_hours = 12.0
    interval_seconds = max(300.0, interval_hours * 3600.0)

    def _loop():
        while True:
            time.sleep(interval_seconds)
            update_ytdlp_if_needed()

    thread = threading.Thread(target=_loop, name="ytdlp-auto-updater", daemon=True)
    thread.start()
    logger.info(f"yt-dlp background auto-updater started (interval: {interval_hours:g}h).")
