"""
OmniParser Client - Client for Microsoft OmniParser v2 via Replicate API.
Analyzes screenshots to detect UI elements with bounding boxes.
"""

import json
import os
import re
import time
import threading
from typing import List, Optional

import httpx
import pyautogui
import replicate

from config import config
from logger import logger

from .models import UIElement, ParsedScreen
from .screen_capturer import capture_screen_data_url


class OmniParserClient:
    """
    Client for OmniParser v2 via Replicate API.
    Analyzes screenshots to detect clickable UI elements.
    """

    # Default model configuration
    DEFAULT_MODEL = "microsoft/omniparser-v2:49cf3d41b8d3aca1360514e83be4c97131ce8f0d99abfc365526d8384caa88df"
    DEFAULT_IMGSZ = 1024
    DEFAULT_BOX_THRESHOLD = 0.05
    DEFAULT_IOU_THRESHOLD = 0.1

    # Retry configuration for API calls
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5
    # Extended timeout: 5 minutes for read, 30s for connect
    API_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        imgsz: Optional[int] = None,
        box_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
    ):
        """
        Initialize the OmniParser client.

        Args:
            api_key: Replicate API key (falls back to env/config)
            model: Model identifier (falls back to config/default)
            imgsz: Image size for processing
            box_threshold: Confidence threshold for bounding boxes
            iou_threshold: IoU threshold for NMS
        """
        # API Key priority: param > env > config
        self.api_key = api_key or config.get_rpa_setting("agentic.replicate_api_key")

        if not self.api_key:
            raise ValueError(
                "Replicate API key not found. Set REPLICATE_API_TOKEN env var or configure in rpa_config.json"
            )

        # Set API token in environment for replicate library
        os.environ["REPLICATE_API_TOKEN"] = self.api_key

        # Model configuration
        self.model = model or config.get_rpa_setting(
            "agentic.omniparser_model", self.DEFAULT_MODEL
        )
        self.imgsz = imgsz or config.get_rpa_setting(
            "agentic.omniparser_imgsz", self.DEFAULT_IMGSZ
        )
        self.box_threshold = box_threshold or config.get_rpa_setting(
            "agentic.omniparser_box_threshold", self.DEFAULT_BOX_THRESHOLD
        )
        self.iou_threshold = iou_threshold or config.get_rpa_setting(
            "agentic.omniparser_iou_threshold", self.DEFAULT_IOU_THRESHOLD
        )

        # Retry settings from config (with defaults)
        self.max_retries = config.get_rpa_setting(
            "agentic.omniparser_max_retries", self.MAX_RETRIES
        )
        self.retry_delay = config.get_rpa_setting(
            "agentic.omniparser_retry_delay", self.RETRY_DELAY_SECONDS
        )

        logger.info(f"[OMNIPARSER] Initialized with model: {self.model[:50]}...")

    def parse_image(
        self, image_data_url: str, screen_size: tuple = None
    ) -> ParsedScreen:
        """
        Parse an image and detect UI elements.
        Includes automatic retry logic for timeout errors.

        Args:
            image_data_url: Image as data URL (data:image/png;base64,...)
            screen_size: Optional screen size (width, height) for coordinate scaling

        Returns:
            ParsedScreen with detected elements

        Raises:
            Exception: If all retry attempts fail
        """
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"[OMNIPARSER] Attempt {attempt}/{self.max_retries} - Sending image for analysis..."
                )

                output = replicate.run(
                    self.model,
                    input={
                        "image": image_data_url,
                        "imgsz": self.imgsz,
                        "box_threshold": self.box_threshold,
                        "iou_threshold": self.iou_threshold,
                    },
                )

                logger.info("[OMNIPARSER] Analysis complete, parsing response...")
                return self._parse_response(output, screen_size)

            except (
                httpx.ReadTimeout,
                httpx.TimeoutException,
                httpx.ConnectTimeout,
            ) as e:
                last_error = e
                logger.warning(
                    f"[OMNIPARSER] Attempt {attempt}/{self.max_retries} timeout: {e}"
                )

                if attempt < self.max_retries:
                    logger.info(
                        f"[OMNIPARSER] Retrying in {self.retry_delay} seconds..."
                    )
                    time.sleep(self.retry_delay)

            except Exception as e:
                error_str = str(e).lower()

                # Handle rate limit errors (Replicate API throttling)
                if "throttled" in error_str or "rate limit" in error_str:
                    last_error = e
                    # Exponential backoff: 5s, 10s, 20s...
                    wait_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[OMNIPARSER] Rate limit hit (attempt {attempt}/{self.max_retries}). "
                        f"Waiting {wait_time}s before retry..."
                    )

                    if attempt < self.max_retries:
                        time.sleep(wait_time)
                        continue
                else:
                    # For other non-recoverable errors, log and re-raise immediately
                    logger.error(f"[OMNIPARSER] API error (non-recoverable): {e}")
                    raise

        # All retries exhausted
        logger.error(
            f"[OMNIPARSER] All {self.max_retries} attempts failed. Last error: {last_error}"
        )
        raise last_error

    def parse_screen(self, screen_size: tuple = None) -> ParsedScreen:
        """
        Capture current screen and parse it.

        Args:
            screen_size: Optional screen size override

        Returns:
            ParsedScreen with detected elements
        """
        # Get actual screen size if not provided
        if screen_size is None:
            screen_size = pyautogui.size()

        # Capture and parse
        data_url = capture_screen_data_url()
        return self.parse_image(data_url, screen_size)

    def _parse_response(self, output: dict, screen_size: tuple = None) -> ParsedScreen:
        """
        Parse the OmniParser API response into structured data.

        The response format is:
        {
            "elements": "icon 0: {'type': 'text', 'bbox': [...], 'interactable': True, 'content': '...'}\n...",
            "img": "data:image/png;base64,..."
        }

        Args:
            output: Raw API response
            screen_size: Screen size for coordinate scaling

        Returns:
            ParsedScreen object
        """
        if screen_size is None:
            screen_size = pyautogui.size()

        elements_str = output.get("elements", "")
        labeled_image_raw = output.get("img")

        # Extract URL from FileOutput object (Replicate returns this type)
        labeled_image_url = None
        if labeled_image_raw:
            if hasattr(labeled_image_raw, "url"):
                # Replicate FileOutput object - extract the URL
                labeled_image_url = labeled_image_raw.url
                logger.info(
                    f"[OMNIPARSER] Labeled image URL extracted: {labeled_image_url[:80]}..."
                )
            elif isinstance(labeled_image_raw, str):
                # Already a string (URL or base64)
                labeled_image_url = labeled_image_raw
                logger.info(
                    f"[OMNIPARSER] Labeled image string received, length: {len(labeled_image_url)}"
                )
            else:
                logger.warning(
                    f"[OMNIPARSER] Unknown labeled_image type: {type(labeled_image_raw).__name__}"
                )
        else:
            logger.warning(
                f"[OMNIPARSER] No labeled image in response. Keys: {list(output.keys())}"
            )

        elements = self._parse_elements_string(elements_str, screen_size)

        logger.info(f"[OMNIPARSER] Parsed {len(elements)} UI elements")

        return ParsedScreen(
            elements=elements,
            screen_size=screen_size,
            raw_response=(
                elements_str[:2000] if elements_str else None
            ),  # Truncate for storage
            labeled_image_url=labeled_image_url,
        )

    def _parse_elements_string(
        self, elements_str: str, screen_size: tuple
    ) -> List[UIElement]:
        """
        Parse the elements string from OmniParser.

        Format: "icon 0: {'type': 'text', 'bbox': [x1, y1, x2, y2], 'content': '...'}\n..."
        Note: bbox values are normalized (0-1), need to scale to screen size
        """
        elements = []
        screen_width, screen_height = screen_size

        if not elements_str:
            return elements

        # Pattern to match each element entry
        # Format: "icon N: {dict}" or "text N: {dict}"
        pattern = r"(?:icon|text)\s+(\d+):\s*(\{[^}]+\})"

        for match in re.finditer(pattern, elements_str, re.DOTALL):
            try:
                element_id = int(match.group(1))
                dict_str = match.group(2)

                # Parse the dict-like string (it's not valid JSON due to single quotes)
                element_data = self._parse_dict_string(dict_str)

                if element_data:
                    # Extract bbox and scale to screen coordinates
                    bbox_normalized = element_data.get("bbox", [0, 0, 0, 0])

                    # Scale bbox from normalized (0-1) to screen pixels
                    if bbox_normalized and len(bbox_normalized) >= 4:
                        x1 = int(bbox_normalized[0] * screen_width)
                        y1 = int(bbox_normalized[1] * screen_height)
                        x2 = int(bbox_normalized[2] * screen_width)
                        y2 = int(bbox_normalized[3] * screen_height)

                        # Calculate center point
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2

                        bbox = [x1, y1, x2, y2]
                    else:
                        bbox = [0, 0, 0, 0]
                        center_x, center_y = 0, 0

                    element = UIElement(
                        id=element_id,
                        type=element_data.get("type", "unknown"),
                        content=element_data.get("content", ""),
                        bbox=bbox,
                        center=(center_x, center_y),
                        interactable=element_data.get("interactable", True),
                    )
                    elements.append(element)

            except Exception as e:
                logger.warning(f"[OMNIPARSER] Failed to parse element: {e}")
                continue

        return elements

    def _parse_dict_string(self, dict_str: str) -> dict:
        """
        Parse a Python dict-like string into an actual dict.
        Handles single quotes and boolean values.
        """
        try:
            # Replace single quotes with double quotes for JSON compatibility
            # But be careful with apostrophes in content
            json_str = dict_str.replace("'", '"')

            # Fix boolean values
            json_str = json_str.replace("True", "true").replace("False", "false")

            return json.loads(json_str)
        except Exception:
            # Fallback: manual parsing for simple cases
            result = {}

            # Extract type
            type_match = re.search(r"'type':\s*'([^']+)'", dict_str)
            if type_match:
                result["type"] = type_match.group(1)

            # Extract content
            content_match = re.search(r"'content':\s*'([^']*)'", dict_str)
            if content_match:
                result["content"] = content_match.group(1)

            # Extract bbox
            bbox_match = re.search(r"'bbox':\s*\[([\d.,\s]+)\]", dict_str)
            if bbox_match:
                try:
                    bbox_values = [
                        float(x.strip()) for x in bbox_match.group(1).split(",")
                    ]
                    result["bbox"] = bbox_values
                except Exception:
                    pass

            # Extract interactable
            interactable_match = re.search(r"'interactable':\s*(True|False)", dict_str)
            if interactable_match:
                result["interactable"] = interactable_match.group(1) == "True"

            return result


# Singleton instance
_client_instance: Optional[OmniParserClient] = None
_warmup_thread: Optional[threading.Thread] = None


def get_omniparser_client() -> OmniParserClient:
    """Get or create the singleton OmniParser client."""
    global _client_instance
    if _client_instance is None:
        _client_instance = OmniParserClient()
    return _client_instance


def start_warmup_async() -> threading.Thread:
    """
    Start OmniParser warmup in a background thread.
    Call this at the beginning of a flow to pre-heat the API.

    Returns:
        The warmup thread (can be joined later if needed)
    """
    global _warmup_thread

    def _do_warmup():
        try:
            client = get_omniparser_client()
            logger.info("[OMNIPARSER] Warmup: Capturing screen...")

            # Capture current screen
            image_data_url = capture_screen_data_url()

            # Parse to warm up the API
            logger.info("[OMNIPARSER] Warmup: Sending to API...")
            result = client.parse_image(image_data_url)

            logger.info(
                f"[OMNIPARSER] Warmup complete - detected {len(result.elements)} elements"
            )
        except Exception as e:
            logger.warning(f"[OMNIPARSER] Warmup failed (non-critical): {e}")

    _warmup_thread = threading.Thread(target=_do_warmup, daemon=True)
    _warmup_thread.start()
    logger.info("[OMNIPARSER] Warmup started in background")
    return _warmup_thread


def wait_for_warmup(timeout: float = 60.0) -> bool:
    """
    Wait for the warmup thread to complete.

    Args:
        timeout: Maximum seconds to wait

    Returns:
        True if warmup completed, False if timed out or no warmup running
    """
    global _warmup_thread

    if _warmup_thread is None:
        return True  # No warmup to wait for

    if not _warmup_thread.is_alive():
        return True  # Already finished

    logger.info(f"[OMNIPARSER] Waiting for warmup to complete (max {timeout}s)...")
    _warmup_thread.join(timeout=timeout)

    if _warmup_thread.is_alive():
        logger.warning("[OMNIPARSER] Warmup still running after timeout")
        return False

    return True
