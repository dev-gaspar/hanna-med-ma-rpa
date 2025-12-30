"""
RPA Tools for Jackson agents.
Used by ReportFinderAgent to interact with the UI.
"""

import pyautogui

from config import config
from logger import logger


def nav_up() -> str:
    """
    Click the UP arrow to navigate to previous document in tree.
    Uses image from rpa_config.json with resolution placeholder.
    """
    image_path = config.get_rpa_setting("images.jackson_nav_arrow_up")
    if not image_path:
        logger.warning("[TOOL] jackson_nav_arrow_up image not configured")
        return "error: image not configured"

    try:
        location = pyautogui.locateOnScreen(image_path, confidence=0.8)
        if location:
            pyautogui.click(pyautogui.center(location))
            logger.info("[TOOL] nav_up: clicked arrow")
            return "success"
        else:
            logger.warning("[TOOL] nav_up: arrow not found on screen")
            return "error: arrow not found"
    except Exception as e:
        logger.error(f"[TOOL] nav_up error: {e}")
        return f"error: {e}"


def nav_down() -> str:
    """
    Click the DOWN arrow to navigate to next document in tree.
    Uses image from rpa_config.json with resolution placeholder.
    """
    image_path = config.get_rpa_setting("images.jackson_nav_arrow_down")
    if not image_path:
        logger.warning("[TOOL] jackson_nav_arrow_down image not configured")
        return "error: image not configured"

    try:
        location = pyautogui.locateOnScreen(image_path, confidence=0.8)
        if location:
            pyautogui.click(pyautogui.center(location))
            logger.info("[TOOL] nav_down: clicked arrow")
            return "success"
        else:
            logger.warning("[TOOL] nav_down: arrow not found on screen")
            return "error: arrow not found"
    except Exception as e:
        logger.error(f"[TOOL] nav_down error: {e}")
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
