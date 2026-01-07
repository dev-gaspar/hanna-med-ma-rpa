"""
RPA Tools for Jackson agents.
Used by ReportFinderAgent to interact with the UI.
"""

import pyautogui

from config import config
from logger import logger


def nav_up(times: int = 1) -> str:
    """
    Click the UP arrow to navigate to previous document in tree.
    Uses image from rpa_config.json with resolution placeholder.

    Args:
        times: Number of times to click the arrow (1-5)
    """
    times = max(1, min(5, times))  # Clamp between 1 and 5
    image_path = config.get_rpa_setting("images.jackson_nav_arrow_up")
    if not image_path:
        logger.warning("[TOOL] jackson_nav_arrow_up image not configured")
        return "error: image not configured"

    try:
        location = pyautogui.locateOnScreen(image_path, confidence=0.8)
        if location:
            center = pyautogui.center(location)
            for i in range(times):
                pyautogui.click(center)
                if times > 1:
                    pyautogui.sleep(0.15)  # Small delay between clicks
            logger.info(f"[TOOL] nav_up: clicked arrow {times}x")
            return "success"
        else:
            logger.warning("[TOOL] nav_up: arrow not found on screen")
            return "error: arrow not found"
    except Exception as e:
        logger.error(f"[TOOL] nav_up error: {e}")
        return f"error: {e}"


def nav_down(times: int = 1) -> str:
    """
    Click the DOWN arrow to navigate to next document in tree.
    Uses image from rpa_config.json with resolution placeholder.

    Args:
        times: Number of times to click the arrow (1-5)
    """
    times = max(1, min(5, times))  # Clamp between 1 and 5
    image_path = config.get_rpa_setting("images.jackson_nav_arrow_down")
    if not image_path:
        logger.warning("[TOOL] jackson_nav_arrow_down image not configured")
        return "error: image not configured"

    try:
        location = pyautogui.locateOnScreen(image_path, confidence=0.8)
        if location:
            center = pyautogui.center(location)
            for i in range(times):
                pyautogui.click(center)
                if times > 1:
                    pyautogui.sleep(0.15)  # Small delay between clicks
            logger.info(f"[TOOL] nav_down: clicked arrow {times}x")
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


def scroll_tree_up(clicks: int = 3) -> str:
    """
    Scroll UP in the notes tree to see folders above the current view.
    First clicks on the tree to ensure it has focus before scrolling.

    Args:
        clicks: Number of scroll clicks (1-5)
    """
    clicks = max(1, min(5, clicks))

    try:
        center = config.get_roi_center("jackson", "notes_tree")
        if not center:
            logger.warning("[TOOL] notes_tree ROI not found, using screen center")
            screen_w, screen_h = pyautogui.size()
            center = (int(screen_w * 0.30), int(screen_h * 0.50))

        # Click first to give focus to the tree (required for scroll to work)
        pyautogui.click(center[0], center[1])
        pyautogui.sleep(0.3)

        # Scroll with aggressive values (100 per click, similar to baptist.py which uses 300)
        scroll_amount = clicks * 100
        pyautogui.scroll(scroll_amount)

        logger.info(
            f"[TOOL] scroll_tree_up: {clicks} clicks ({scroll_amount}) at {center}"
        )
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] scroll_tree_up error: {e}")
        return f"error: {e}"


def scroll_tree_down(clicks: int = 3) -> str:
    """
    Scroll DOWN in the notes tree to see folders below the current view.
    First clicks on the tree to ensure it has focus before scrolling.

    Args:
        clicks: Number of scroll clicks (1-5)
    """
    clicks = max(1, min(5, clicks))

    try:
        center = config.get_roi_center("jackson", "notes_tree")
        if not center:
            logger.warning("[TOOL] notes_tree ROI not found, using screen center")
            screen_w, screen_h = pyautogui.size()
            center = (int(screen_w * 0.30), int(screen_h * 0.50))

        # Click first to give focus to the tree (required for scroll to work)
        pyautogui.click(center[0], center[1])
        pyautogui.sleep(0.3)

        # Scroll with aggressive values (100 per click, similar to baptist.py which uses 300)
        scroll_amount = clicks * 100
        pyautogui.scroll(-scroll_amount)

        logger.info(
            f"[TOOL] scroll_tree_down: {clicks} clicks ({scroll_amount}) at {center}"
        )
        return "success"
    except Exception as e:
        logger.error(f"[TOOL] scroll_tree_down error: {e}")
        return f"error: {e}"
