"""
Screen Capturer - Utilities for capturing screenshots.
Provides methods to capture screen in various formats for OmniParser and debugging.
"""

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import pyautogui
from PIL import Image

from logger import logger
from config import config


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

    def _save_debug(self, image: Image.Image, prefix: str = "capture") -> None:
        """Save a debug copy of the screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        debug_path = self.debug_folder / f"{prefix}_{timestamp}.png"
        image.save(str(debug_path))
        logger.debug(f"[SCREEN] Debug screenshot saved: {debug_path}")

    def capture_with_mask(self, rois: List["ROI"]) -> Image.Image:
        """
        Capture screen with only ROI regions visible, rest is white.

        This allows OmniParser to focus only on relevant areas while
        keeping absolute coordinates (no transformation needed).

        Args:
            rois: List of ROI regions to keep visible

        Returns:
            PIL Image with only ROIs visible, rest white
        """
        from agentic.models import ROI

        screenshot = self.capture()
        masked = Image.new("RGB", screenshot.size, (255, 255, 255))

        for roi in rois:
            region = screenshot.crop(roi.bbox)
            masked.paste(region, (roi.x, roi.y))
            logger.debug(f"[SCREEN] ROI applied: ({roi.x}, {roi.y}, {roi.w}x{roi.h})")

        logger.info(f"[SCREEN] Captured with {len(rois)} ROI mask(s)")

        if self.save_debug_screenshots:
            self._save_debug(masked, prefix="masked")

        return masked

    def capture_with_mask_base64(self, rois: List["ROI"], format: str = "PNG") -> str:
        """Capture with ROI mask and return as base64."""
        screenshot = self.capture_with_mask(rois)
        buffered = BytesIO()
        screenshot.save(buffered, format=format)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def capture_with_mask_data_url(self, rois: List["ROI"], format: str = "PNG") -> str:
        """Capture with ROI mask and return as data URL."""
        b64 = self.capture_with_mask_base64(rois, format)
        return f"data:image/{format.lower()};base64,{b64}"

    def enhance_for_ocr(
        self,
        image: Image.Image,
        upscale_factor: float = 2.0,
        contrast_factor: float = 1.3,
        sharpness_factor: float = 1.5,
    ) -> Image.Image:
        """
        Enhance image for better OCR detection in VDI environments.

        Applies upscaling, contrast enhancement, and sharpening to improve
        text detection in low-resolution or compressed VDI screenshots.

        Args:
            image: PIL Image to enhance
            upscale_factor: Scale factor for upscaling (default 2.0 = 2x size)
            contrast_factor: Contrast multiplier (default 1.3 = 30% more contrast)
            sharpness_factor: Sharpness multiplier (default 1.5 = 50% sharper)

        Returns:
            Enhanced PIL Image
        """
        from PIL import ImageEnhance

        # Step 1: Upscale with high-quality interpolation
        if upscale_factor > 1.0:
            new_size = (
                int(image.width * upscale_factor),
                int(image.height * upscale_factor),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"[SCREEN] Upscaled to {new_size}")

        # Step 2: Enhance contrast
        if contrast_factor != 1.0:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(contrast_factor)
            logger.debug(f"[SCREEN] Contrast enhanced by {contrast_factor}x")

        # Step 3: Sharpen
        if sharpness_factor != 1.0:
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(sharpness_factor)
            logger.debug(f"[SCREEN] Sharpness enhanced by {sharpness_factor}x")

        return image

    def capture_with_mask_enhanced_base64(
        self,
        rois: List["ROI"],
        enhance: bool = True,
        upscale_factor: float = 2.0,
        contrast_factor: float = 1.3,
        sharpness_factor: float = 1.5,
        format: str = "PNG",
    ) -> str:
        """
        Capture with ROI mask, apply enhancements, and return as base64.

        This is the recommended method for VDI environments where OCR struggles
        with low resolution and compressed images.

        Args:
            rois: List of ROI regions to keep visible
            enhance: Whether to apply OCR enhancement (default True)
            upscale_factor: Scale factor for upscaling
            contrast_factor: Contrast multiplier
            sharpness_factor: Sharpness multiplier
            format: Image format (PNG, JPEG)

        Returns:
            Base64 encoded enhanced image
        """
        screenshot = self.capture_with_mask(rois)

        if enhance:
            screenshot = self.enhance_for_ocr(
                screenshot,
                upscale_factor=upscale_factor,
                contrast_factor=contrast_factor,
                sharpness_factor=sharpness_factor,
            )
            logger.info("[SCREEN] Applied VDI OCR enhancement")

            if self.save_debug_screenshots:
                self._save_debug(screenshot, prefix="enhanced")

        buffered = BytesIO()
        screenshot.save(buffered, format=format)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")


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


def get_agent_rois(emr: str, agent: str) -> List["ROI"]:
    """
    Get ROI regions configured for a specific agent.

    Args:
        emr: EMR type (jackson, baptist, etc.)
        agent: Agent name (patient_finder, report_finder, etc.)

    Returns:
        List of ROI objects, empty if not configured
    """
    from agentic.models import ROI

    resolution = config.get_rpa_setting("screen_resolution", "1024x768")

    try:
        roi_definitions = config.get_rpa_setting("roi_definitions", {})
        roi_regions = config.get_rpa_setting("roi_regions", {})

        region_names = roi_definitions.get(emr, {}).get(resolution, {}).get(agent, [])
        regions = roi_regions.get(emr, {}).get(resolution, {})

        rois = [ROI(**regions[name]) for name in region_names if name in regions]

        if rois:
            logger.info(
                f"[ROI] Loaded {len(rois)} regions for {emr}/{agent}: {region_names}"
            )

        return rois
    except Exception as e:
        logger.warning(f"[ROI] Error loading ROIs for {emr}/{agent}: {e}")
        return []
