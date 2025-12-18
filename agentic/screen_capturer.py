"""
Screen Capturer - Utilities for capturing screenshots.
Provides methods to capture screen in various formats for OmniParser and debugging.
"""

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import pyautogui
from PIL import Image

from logger import logger


class ScreenCapturer:
    """
    Utility class for capturing screenshots.
    Provides multiple output formats for different use cases.
    """

    def __init__(
        self, save_debug_screenshots: bool = False, debug_folder: str = "screenshots"
    ):
        """
        Initialize the screen capturer.

        Args:
            save_debug_screenshots: If True, saves a copy of each capture for debugging
            debug_folder: Folder to save debug screenshots
        """
        self.save_debug_screenshots = save_debug_screenshots
        self.debug_folder = Path(debug_folder)

        if self.save_debug_screenshots:
            self.debug_folder.mkdir(parents=True, exist_ok=True)

    def capture(self) -> Image.Image:
        """
        Capture the current screen.

        Returns:
            PIL Image of the current screen
        """
        screenshot = pyautogui.screenshot()
        logger.info(f"[SCREEN] Captured screenshot: {screenshot.size}")

        if self.save_debug_screenshots:
            self._save_debug(screenshot)

        return screenshot

    def capture_base64(self, format: str = "PNG") -> str:
        """
        Capture screen and return as base64 string.

        Args:
            format: Image format (PNG, JPEG)

        Returns:
            Base64 encoded image string
        """
        screenshot = self.capture()
        buffered = BytesIO()
        screenshot.save(buffered, format=format)
        b64_string = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return b64_string

    def capture_data_url(self, format: str = "PNG") -> str:
        """
        Capture screen and return as data URL for API calls.

        Args:
            format: Image format (PNG, JPEG)

        Returns:
            Data URL string (data:image/png;base64,...)
        """
        b64_string = self.capture_base64(format)
        mime_type = f"image/{format.lower()}"
        return f"data:{mime_type};base64,{b64_string}"

    def capture_bytes(self, format: str = "PNG") -> bytes:
        """
        Capture screen and return as bytes.

        Args:
            format: Image format (PNG, JPEG)

        Returns:
            Raw image bytes
        """
        screenshot = self.capture()
        buffered = BytesIO()
        screenshot.save(buffered, format=format)
        return buffered.getvalue()

    def get_screen_size(self) -> Tuple[int, int]:
        """
        Get the current screen size.

        Returns:
            Tuple of (width, height)
        """
        return pyautogui.size()

    def save_screenshot(self, path: str, format: str = "PNG") -> str:
        """
        Capture and save screenshot to file.

        Args:
            path: File path to save to
            format: Image format

        Returns:
            Absolute path to saved file
        """
        screenshot = self.capture()
        full_path = Path(path).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(str(full_path), format=format)
        logger.info(f"[SCREEN] Saved screenshot to: {full_path}")
        return str(full_path)

    def _save_debug(self, image: Image.Image) -> None:
        """Save a debug copy of the screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        debug_path = self.debug_folder / f"capture_{timestamp}.png"
        image.save(str(debug_path))
        logger.debug(f"[SCREEN] Debug screenshot saved: {debug_path}")


# Singleton instance for convenience
_default_capturer: Optional[ScreenCapturer] = None


def get_screen_capturer(save_debug: bool = False) -> ScreenCapturer:
    """
    Get the default screen capturer instance.

    Args:
        save_debug: Whether to save debug screenshots

    Returns:
        ScreenCapturer instance
    """
    global _default_capturer
    if _default_capturer is None:
        _default_capturer = ScreenCapturer(save_debug_screenshots=save_debug)
    return _default_capturer


def capture_screen_base64() -> str:
    """Convenience function to capture screen as base64."""
    return get_screen_capturer().capture_base64()


def capture_screen_data_url() -> str:
    """Convenience function to capture screen as data URL."""
    return get_screen_capturer().capture_data_url()
