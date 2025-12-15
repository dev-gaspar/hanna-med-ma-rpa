"""
Windows-specific system utilities for RPA.
Handles keep-awake functionality and low-level input simulation.
"""

import platform

# Windows-specific imports
if platform.system() == "Windows":
    import ctypes
    from ctypes import wintypes

    # Windows API constants for SendInput
    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008

    # Virtual key codes
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_MENU = 0x12  # ALT key
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    VK_UP = 0x26
    VK_DOWN = 0x28
    VK_F5 = 0x74

    # Define Windows structures
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        _anonymous_ = ("_input",)
        _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

else:
    # Stub definitions for non-Windows platforms
    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_MENU = 0x12
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    VK_UP = 0x26
    VK_DOWN = 0x28
    VK_F5 = 0x74

    class KEYBDINPUT:
        pass

    class INPUT:
        pass


# --- Keep System Awake Functions ---
# Constants for Windows SetThreadExecutionState
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040


def keep_system_awake():
    """
    Prevents Windows from going to sleep or turning off the display.
    Uses Windows API - much better than moving the mouse!
    """
    if platform.system() == "Windows":
        try:
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            # Keeps system and display awake continuously
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
            print("[AWAKE] System kept awake - sleep and screen timeout disabled")
            return True
        except Exception as e:
            print(f"[AWAKE] Warning: Could not set awake state: {e}")
            return False
    else:
        print("[AWAKE] Keep awake only supported on Windows")
        return False


def allow_system_sleep():
    """
    Allows Windows to sleep normally again.
    Call this when RPA finishes.
    """
    if platform.system() == "Windows":
        try:
            # Reset to normal - allows sleep
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            print("[AWAKE] System can sleep normally now")
            return True
        except Exception as e:
            print(f"[AWAKE] Warning: Could not reset awake state: {e}")
            return False
    return False


def send_key_windows(vk_code):
    """
    Send a key using Windows SendInput API (works better in VDI).
    vk_code: Virtual key code (e.g., VK_TAB, VK_RETURN)
    """
    if platform.system() != "Windows":
        raise Exception("send_key_windows only works on Windows")

    # Create input for key down
    input_down = INPUT()
    input_down.type = INPUT_KEYBOARD
    input_down.ki = KEYBDINPUT(vk_code, 0, 0, 0, None)

    # Create input for key up
    input_up = INPUT()
    input_up.type = INPUT_KEYBOARD
    input_up.ki = KEYBDINPUT(vk_code, 0, KEYEVENTF_KEYUP, 0, None)

    # Send both inputs
    inputs = (INPUT * 2)(input_down, input_up)
    ctypes.windll.user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def send_text_windows(text):
    """
    Send text using Windows SendInput API with UNICODE (works in VDI).
    This sends actual Unicode characters, not virtual key codes.
    """
    if platform.system() != "Windows":
        raise Exception("send_text_windows only works on Windows")

    inputs_list = []
    for char in text:
        # Key down
        input_down = INPUT()
        input_down.type = INPUT_KEYBOARD
        input_down.ki = KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE, 0, None)
        inputs_list.append(input_down)

        # Key up
        input_up = INPUT()
        input_up.type = INPUT_KEYBOARD
        input_up.ki = KEYBDINPUT(
            0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None
        )
        inputs_list.append(input_up)

    # Send all inputs at once
    inputs_array = (INPUT * len(inputs_list))(*inputs_list)
    ctypes.windll.user32.SendInput(
        len(inputs_list), ctypes.byref(inputs_array), ctypes.sizeof(INPUT)
    )
