"""
VDI-compatible input methods.
Provides reliable text input and key presses for VDI/Citrix environments.
"""

import pyautogui
import pydirectinput
import pyperclip

from logger import logger

from .system_utils import (
    send_key_windows,
    send_text_windows,
    VK_TAB,
    VK_RETURN,
    VK_LEFT,
    VK_RIGHT,
    VK_UP,
    VK_DOWN,
    VK_F5,
)


def stoppable_sleep(duration_s, check_interval_s=0.1):
    """
    Replacement of time.sleep() that can be interrupted by check_should_stop().
    Imported here and re-exported for convenience.
    """
    import time
    from .rpa_engine import check_should_stop

    start_time = time.time()
    while (time.time() - start_time) < duration_s:
        check_should_stop()

        # Calculate how much to sleep to avoid going over
        remaining = duration_s - (time.time() - start_time)
        sleep_for = min(check_interval_s, remaining)

        if sleep_for <= 0:
            break

        time.sleep(sleep_for)


def type_with_clipboard(text):
    """
    Type text using hybrid approach for VDI compatibility.
    - Uses clipboard (Ctrl+V) which works best in VDI browsers
    - Slow delays for clipboard sync across VDI layers
    """
    logger.debug(
        f"[TYPE_CLIP] Typing text: '{text[:50]}{'...' if len(text) > 50 else ''}'"
    )

    try:
        # Clear clipboard first to avoid stale data
        pyperclip.copy("")
        stoppable_sleep(1.0)  # Wait for clipboard to clear

        # Copy new text to clipboard
        pyperclip.copy(text)

        # LONGER WAIT: Allow clipboard to sync through AnyDesk -> VM -> Browser -> VDI
        stoppable_sleep(4.0)

        # Use pydirectinput for Ctrl+V (more reliable than pyautogui in VDI)
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("v")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")

        logger.debug("[TYPE_CLIP] Text pasted successfully")

        # LONGER WAIT: Allow VDI to process the paste before next operation
        stoppable_sleep(1.0)

    except Exception as e:
        logger.warning(
            f"[TYPE_CLIP] Failed to paste text: {e}, falling back to SendInput"
        )
        try:
            send_text_windows(text)
        except Exception as e2:
            logger.error(f"[TYPE_CLIP] Fallback also failed: {e2}")
            raise


def press_key_vdi(key_name):
    """
    Press a key in VDI environment using pydirectinput (DirectInput).
    DirectInput works better than SendInput for VDI environments.
    """
    try:
        pydirectinput.press(key_name)
        stoppable_sleep(0.2)
    except Exception as e:
        logger.warning(
            f"[KEY_PRESS] pydirectinput failed: {e}, falling back to SendInput"
        )

        # Fallback to SendInput
        key_map = {
            "tab": VK_TAB,
            "enter": VK_RETURN,
            "return": VK_RETURN,
            "left": VK_LEFT,
            "right": VK_RIGHT,
            "up": VK_UP,
            "down": VK_DOWN,
            "f5": VK_F5,
        }

        key_lower = key_name.lower()
        if key_lower not in key_map:
            raise ValueError(f"Unknown key: {key_name}")

        try:
            vk_code = key_map[key_lower]
            send_key_windows(vk_code)
            stoppable_sleep(0.2)
        except Exception as e2:
            logger.error(f"[KEY_PRESS] Fallback also failed: {e2}")
            raise


def type_via_alt_codes(text):
    """
    Type text using Alt+Numpad codes.
    Bypasses most VDI restrictions since it simulates hardware numpad.
    Requires NumLock to be enabled.
    """
    for char in text:
        # Get ASCII code
        code = ord(char)
        s_code = str(code)

        # Hold ALT
        pydirectinput.keyDown("alt")

        # Type code on Numpad
        for digit in s_code:
            # Map digits to numpad keys (e.g., '1' -> 'num1')
            numpad_key = f"num{digit}"
            pydirectinput.press(numpad_key)
            stoppable_sleep(0.02)

        # Release ALT
        pydirectinput.keyUp("alt")

        # Small pause between characters
        stoppable_sleep(0.1)
