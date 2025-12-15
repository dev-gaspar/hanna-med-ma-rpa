"""
Hanna-Med RPA Agent - Main Entry Point

This module provides backward compatibility with the original app.py interface
while using the new modular architecture.

For direct API access, use:
    from api import app, create_app

For flow access, use:
    from flows import BaptistFlow, JacksonFlow, StewardFlow
"""

import signal
import sys

# Load environment variables including credentials
from config import config

# --- Signal Handling ---
original_sigint = signal.getsignal(signal.SIGINT)


def signal_handler(sig, frame):
    """Signal handler for Ctrl+C."""
    from core.rpa_engine import rpa_should_stop, set_should_stop

    # Avoid double execution if already stopping
    if rpa_should_stop:
        return

    print("\n\n[SIGNAL]    Ctrl+C detected - Stopping RPA...")
    set_should_stop(True)

    # Call the original uvicorn handler so the server stops
    if callable(original_sigint):
        original_sigint(sig, frame)
    else:
        sys.exit(0)


# Register the signal handler (only works in main thread)
try:
    signal.signal(signal.SIGINT, signal_handler)
except ValueError:
    # Signal handlers only work in main thread, skip if imported from thread
    pass

# --- Import and expose the FastAPI app ---
from api import app, create_app

# --- Backward compatibility exports ---
# These allow old code that imports from app.py to continue working

from core.rpa_engine import (
    rpa_state,
    rpa_should_stop,
    check_should_stop,
    stoppable_sleep,
    RPABotBase,
)

from core.system_utils import (
    keep_system_awake,
    allow_system_sleep,
)

from core.vdi_input import (
    type_with_clipboard,
    press_key_vdi,
)

from core.s3_client import (
    S3Client,
    get_s3_client,
)

from flows import (
    BaptistFlow,
    JacksonFlow,
    StewardFlow,
    get_flow,
)


# Legacy function aliases for backward compatibility
def take_screenshot():
    """Legacy wrapper - use S3Client.take_screenshot() instead."""
    return get_s3_client().take_screenshot()


def upload_to_s3(img_buffer, filename):
    """Legacy wrapper - use S3Client.upload_image() instead."""
    return get_s3_client().upload_image(img_buffer, filename)


def upload_pdf_to_s3(file_path, s3_filename):
    """Legacy wrapper - use S3Client.upload_pdf() instead."""
    return get_s3_client().upload_pdf(file_path, s3_filename)


def generate_presigned_url(filename, expiration=86400):
    """Legacy wrapper - use S3Client.generate_presigned_url() instead."""
    return get_s3_client().generate_presigned_url(filename, expiration)


def capture_screenshot_for_hospital(
    hospital_full_name, display_name, hospital_index, execution_id
):
    """Legacy wrapper - use S3Client.capture_screenshot_for_hospital() instead."""
    return get_s3_client().capture_screenshot_for_hospital(
        hospital_full_name, display_name, hospital_index, execution_id
    )


# Legacy flow runners for backward compatibility
def run_baptist_health_flow():
    """Legacy wrapper - use BaptistFlow().run() instead."""
    flow = BaptistFlow()
    flow.run(
        rpa_state["execution_id"],
        rpa_state["sender"],
        rpa_state["instance"],
        rpa_state["trigger_type"],
    )


def run_jackson_flow():
    """Legacy wrapper - use JacksonFlow().run() instead."""
    flow = JacksonFlow()
    flow.run(
        rpa_state["execution_id"],
        rpa_state["sender"],
        rpa_state["instance"],
        rpa_state["trigger_type"],
    )


def run_steward_flow():
    """Legacy wrapper - use StewardFlow().run() instead."""
    flow = StewardFlow()
    flow.run(
        rpa_state["execution_id"],
        rpa_state["sender"],
        rpa_state["instance"],
        rpa_state["trigger_type"],
    )


__all__ = [
    # FastAPI
    "app",
    "create_app",
    # State
    "rpa_state",
    "rpa_should_stop",
    "check_should_stop",
    "stoppable_sleep",
    # Core
    "RPABotBase",
    "keep_system_awake",
    "allow_system_sleep",
    "type_with_clipboard",
    "press_key_vdi",
    # S3
    "S3Client",
    "get_s3_client",
    "take_screenshot",
    "upload_to_s3",
    "upload_pdf_to_s3",
    "generate_presigned_url",
    "capture_screenshot_for_hospital",
    # Flows
    "BaptistFlow",
    "JacksonFlow",
    "StewardFlow",
    "get_flow",
    "run_baptist_health_flow",
    "run_jackson_flow",
    "run_steward_flow",
]
