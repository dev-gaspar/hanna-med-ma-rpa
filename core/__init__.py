"""
Core RPA module - Base utilities and infrastructure.
"""

from .rpa_engine import RPABotBase, rpa_state, rpa_should_stop, set_should_stop
from .system_utils import (
    keep_system_awake,
    allow_system_sleep,
    send_key_windows,
    send_text_windows,
    INPUT,
    KEYBDINPUT,
    VK_TAB,
    VK_RETURN,
    VK_CONTROL,
    VK_SHIFT,
    VK_MENU,
    VK_LEFT,
    VK_RIGHT,
    VK_UP,
    VK_DOWN,
    VK_F5,
)
from .vdi_input import type_with_clipboard, press_key_vdi, type_via_alt_codes
from .s3_client import S3Client

__all__ = [
    "RPABotBase",
    "rpa_state",
    "rpa_should_stop",
    "set_should_stop",
    "keep_system_awake",
    "allow_system_sleep",
    "send_key_windows",
    "send_text_windows",
    "type_with_clipboard",
    "press_key_vdi",
    "type_via_alt_codes",
    "S3Client",
]
