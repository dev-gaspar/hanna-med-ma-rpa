"""
RPA Tools for Steward agents (Meditech).
Used by agents to interact with the Meditech UI.
"""

import pyautogui

from config import config
from logger import logger


def move_to_center(roi_name: str) -> str:
    """
    Move cursor to center of ROI without clicking.
    Used to position cursor for scroll without accidentally clicking on elements.

    Args:
        roi_name: ROI name to get center position from config

    Returns:
        "success" or error message
    """
    try:
        center = config.get_roi_center("steward", roi_name)
        if not center:
            logger.warning(f"[TOOL] {roi_name} ROI not found, using screen center")
            screen_w, screen_h = pyautogui.size()
            center = (int(screen_w * 0.50), int(screen_h * 0.50))

        pyautogui.moveTo(center[0], center[1])
        logger.info(f"[TOOL] Moved cursor to center of {roi_name}: {center}")
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] move_to_center error: {e}")
        return f"error: {e}"


def click_element(element_id: int, elements: list, action: str = "click") -> str:
    """
    Click or double-click on an element by its OmniParser ID.

    Args:
        element_id: The OmniParser element ID
        elements: List of parsed UI elements
        action: "click" or "dblclick"

    Returns:
        "success" or error message
    """
    # Find element by ID
    target = None
    for el in elements:
        if el.get("id") == element_id:
            target = el
            break

    if not target:
        logger.warning(f"[TOOL] Element {element_id} not found")
        return f"error: element {element_id} not found"

    center = target.get("center", [0, 0])
    x, y = int(center[0]), int(center[1])

    try:
        if action == "dblclick":
            pyautogui.doubleClick(x, y)
            logger.info(f"[TOOL] Double-clicked element {element_id} at ({x}, {y})")
        else:
            pyautogui.click(x, y)
            logger.info(f"[TOOL] Clicked element {element_id} at ({x}, {y})")
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] Click error: {e}")
        return f"error: {e}"


def scroll_down(clicks: int = 3, roi_name: str = None) -> str:
    """
    Scroll DOWN in the current view.
    Moves cursor to center of ROI WITHOUT clicking, then scrolls.

    Args:
        clicks: Number of scroll clicks (1-10)
        roi_name: Optional ROI name to get center position from config
    """
    clicks = max(1, min(10, clicks))

    try:
        if roi_name:
            center = config.get_roi_center("steward", roi_name)
            if not center:
                logger.warning(f"[TOOL] {roi_name} ROI not found, using screen center")
                screen_w, screen_h = pyautogui.size()
                center = (int(screen_w * 0.50), int(screen_h * 0.50))
        else:
            screen_w, screen_h = pyautogui.size()
            center = (int(screen_w * 0.50), int(screen_h * 0.50))

        # Move cursor to center WITHOUT clicking (avoid unintended clicks)
        pyautogui.moveTo(center[0], center[1])
        pyautogui.sleep(0.2)

        # Scroll DOWN (negative value) - 1800 per click for fast scrolling
        scroll_amount = clicks * 1800
        pyautogui.scroll(-scroll_amount)

        logger.info(
            f"[TOOL] scroll_down: {clicks} clicks ({scroll_amount}) at {center}"
        )
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] scroll_down error: {e}")
        return f"error: {e}"


def scroll_up(clicks: int = 3, roi_name: str = None) -> str:
    """
    Scroll UP in the current view.
    Moves cursor to center of ROI WITHOUT clicking, then scrolls.

    Args:
        clicks: Number of scroll clicks (1-10)
        roi_name: Optional ROI name to get center position from config
    """
    clicks = max(1, min(10, clicks))

    try:
        if roi_name:
            center = config.get_roi_center("steward", roi_name)
            if not center:
                logger.warning(f"[TOOL] {roi_name} ROI not found, using screen center")
                screen_w, screen_h = pyautogui.size()
                center = (int(screen_w * 0.50), int(screen_h * 0.50))
        else:
            screen_w, screen_h = pyautogui.size()
            center = (int(screen_w * 0.50), int(screen_h * 0.50))

        # Move cursor to center WITHOUT clicking (avoid unintended clicks)
        pyautogui.moveTo(center[0], center[1])
        pyautogui.sleep(0.2)

        # Scroll UP (positive value) - 1800 per click for fast scrolling
        scroll_amount = clicks * 1800
        pyautogui.scroll(scroll_amount)

        logger.info(f"[TOOL] scroll_up: {clicks} clicks ({scroll_amount}) at {center}")
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] scroll_up error: {e}")
        return f"error: {e}"
