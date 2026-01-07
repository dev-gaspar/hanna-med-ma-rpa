"""
Base RPA Engine - Core class with common utilities.
Provides foundational methods for all RPA flows.
"""

import time
import threading
import pyautogui

from config import config


# --- Global State ---
rpa_should_stop = False
rpa_state = {
    "status": "idle",
    "execution_id": None,
    "current_step": None,
    "sender": None,
    "instance": None,
    "trigger_type": None,
}

# --- Queue System for Batch Processing ---
rpa_queue: list = []  # List of pending requests
rpa_queue_lock = threading.Lock()  # Thread safety for queue operations
_queue_processor_active = False  # Flag to prevent multiple processors


def enqueue_request(request_data: dict) -> int:
    """
    Add a request to the queue.

    Args:
        request_data: Dict with hospital_type, execution_id, sender, etc.

    Returns:
        Position in queue (1-indexed)
    """
    with rpa_queue_lock:
        rpa_queue.append(request_data)
        return len(rpa_queue)


def dequeue_request() -> dict | None:
    """
    Get the next request from the queue.

    Returns:
        Request dict or None if queue is empty
    """
    with rpa_queue_lock:
        return rpa_queue.pop(0) if rpa_queue else None


def get_queue_status() -> dict:
    """
    Get current queue status.

    Returns:
        Dict with pending count, current status, and queued hospitals
    """
    with rpa_queue_lock:
        return {
            "pending": len(rpa_queue),
            "current_status": rpa_state["status"],
            "queue": [r.get("hospital_type") for r in rpa_queue],
        }


def clear_queue() -> int:
    """
    Clear all pending requests from the queue.

    Returns:
        Number of cleared requests
    """
    with rpa_queue_lock:
        count = len(rpa_queue)
        rpa_queue.clear()
        return count


def enqueue_and_should_start_processor(request_data: dict) -> tuple[int, bool]:
    """
    Atomically enqueue a request and determine if a processor should start.

    This prevents race conditions where multiple processors could be started
    when several requests arrive simultaneously.

    Args:
        request_data: Dict with hospital_type, execution_id, sender, etc.

    Returns:
        Tuple of (position, should_start_processor)
    """
    global _queue_processor_active
    with rpa_queue_lock:
        rpa_queue.append(request_data)
        position = len(rpa_queue)

        # Only start processor if none is active
        should_start = False
        if not _queue_processor_active:
            _queue_processor_active = True
            should_start = True

        return position, should_start


def mark_processor_finished():
    """Mark the queue processor as finished, allowing a new one to start."""
    global _queue_processor_active
    with rpa_queue_lock:
        _queue_processor_active = False


def set_should_stop(value: bool):
    """Set the global should_stop flag."""
    global rpa_should_stop
    rpa_should_stop = value


def check_should_stop():
    """Checks if the RPA should stop and raises an exception."""
    global rpa_should_stop
    if rpa_should_stop:
        print("[STOP] RPA stopped by user")
        # Clear the flag for the uvicorn handler
        rpa_should_stop = False
        raise KeyboardInterrupt("RPA stopped by Ctrl+C")


def stoppable_sleep(duration_s, check_interval_s=0.1):
    """
    Replacement of time.sleep() that can be interrupted by check_should_stop().
    """
    start_time = time.time()
    while (time.time() - start_time) < duration_s:
        check_should_stop()

        # Calculate how much to sleep to avoid going over
        remaining = duration_s - (time.time() - start_time)
        sleep_for = min(check_interval_s, remaining)

        if sleep_for <= 0:
            break

        time.sleep(sleep_for)


class RPABotBase:
    """
    Base class for RPA bots providing common utilities.
    All hospital-specific flows should inherit from this.
    """

    def __init__(self):
        self.should_stop = False
        self.confidence = config.get_rpa_setting("confidence", 0.8)

    def start_session(self):
        """Start RPA session - keeps system awake."""
        from .system_utils import keep_system_awake

        keep_system_awake()

    def end_session(self):
        """End RPA session - allows system to sleep."""
        from .system_utils import allow_system_sleep

        allow_system_sleep()

    def check_stop(self):
        """Check if RPA should stop and raise exception if so."""
        check_should_stop()

    def stoppable_sleep(self, duration_s, check_interval_s=0.1):
        """Sleep that can be interrupted."""
        stoppable_sleep(duration_s, check_interval_s)

    def wait_for_element(
        self,
        image_path,
        timeout=None,
        confidence=None,
        check_interval=0.5,
        description="element",
        auto_click=False,
    ):
        """Wait until an element appears on screen."""
        if timeout is None:
            timeout = config.get_timeout("default")
        if confidence is None:
            confidence = self.confidence

        print(f"[WAIT] Waiting for {description} (timeout: {timeout}s)")
        start_time = time.time()
        attempts = 0

        while (time.time() - start_time) < timeout:
            self.check_stop()

            try:
                location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                if location:
                    elapsed = round(time.time() - start_time, 1)
                    print(f"[WAIT] {description} found after {elapsed}s")
                    self.stoppable_sleep(1)
                    try:
                        confirmed_location = (
                            pyautogui.locateOnScreen(image_path, confidence=confidence)
                            or location
                        )
                    except Exception:
                        confirmed_location = location
                    self.stoppable_sleep(1)
                    if auto_click and confirmed_location:
                        self.safe_click(confirmed_location, description)
                    return confirmed_location
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as e:
                print(f"[WAIT] Error: {str(e)}")

            attempts += 1
            time.sleep(check_interval)

        print(f"[WAIT] Timeout: {description} not found")
        return None

    def robust_wait_for_element(
        self,
        target_image_path,
        target_description,
        handlers,
        timeout=None,
        confidence=None,
        check_interval=0.5,
        auto_click=False,
    ):
        """
        Wait for a target element, handling obstacles through handlers.

        Args:
            target_image_path: Target image to find
            target_description: Description of the target (for logs)
            handlers: Map of obstacles -> (description, handler_function)
            timeout: Maximum total wait time

        Returns:
            Location of target element, or None if failed
        """
        if timeout is None:
            timeout = config.get_timeout("default")
        if confidence is None:
            confidence = self.confidence

        print(f"[WAIT-R] Waiting for {target_description} (handling obstacles)")
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            self.check_stop()
            try:
                # Search for the primary target
                location = pyautogui.locateOnScreen(
                    target_image_path, confidence=confidence
                )
                if location:
                    elapsed = round(time.time() - start_time, 1)
                    print(
                        f"[WAIT-R] Target {target_description} found after {elapsed}s"
                    )
                    self.stoppable_sleep(1)
                    try:
                        confirmed_location = (
                            pyautogui.locateOnScreen(
                                target_image_path, confidence=confidence
                            )
                            or location
                        )
                    except Exception:
                        confirmed_location = location
                    self.stoppable_sleep(1)
                    if auto_click and confirmed_location:
                        self.safe_click(confirmed_location, target_description)
                    return confirmed_location
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as e:
                print(f"[WAIT-R] Error: {str(e)}")

            # If not found, search for obstacles
            obstacle_handled = False
            for obstacle_image, (obs_desc, handler_func) in handlers.items():
                try:
                    obstacle_loc = pyautogui.locateOnScreen(
                        obstacle_image, confidence=confidence
                    )
                    if obstacle_loc:
                        print(f"\n[HANDLER] Obstacle detected: {obs_desc}")
                        handler_func(obstacle_loc)
                        print(f"[HANDLER] Obstacle {obs_desc} handled, retrying...")
                        obstacle_handled = True
                        break
                except pyautogui.ImageNotFoundException:
                    continue
                except Exception as e:
                    print(f"[HANDLER] Error: {str(e)}")

            if not obstacle_handled:
                time.sleep(check_interval)

        print(f"[WAIT-R] Timeout: {target_description} not found")
        return None

    def wait_for_element_disappear(
        self,
        image_path,
        timeout=30,
        confidence=None,
        check_interval=0.5,
        description="element",
    ):
        """Wait until an element disappears from the screen."""
        if confidence is None:
            confidence = self.confidence

        print(f"[WAIT] Waiting for {description} to disappear")
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            self.check_stop()

            try:
                location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                if not location:
                    elapsed = round(time.time() - start_time, 1)
                    print(f"[WAIT] {description} disappeared after {elapsed}s")
                    return True
            except pyautogui.ImageNotFoundException:
                elapsed = round(time.time() - start_time, 1)
                print(f"[WAIT] {description} disappeared after {elapsed}s")
                return True
            except Exception as e:
                print(f"[WAIT] Error: {str(e)}")

            time.sleep(check_interval)

        print(f"[WAIT] Timeout: {description} still visible")
        return False

    def safe_click(self, location, description="element", retries=None, delay=None):
        """Safely click on a location."""
        if retries is None:
            retries = config.get_rpa_setting("retry.max_attempts", 3)
        if delay is None:
            delay = config.get_rpa_setting("retry.delay_seconds", 0.5)

        for attempt in range(retries):
            self.check_stop()

            try:
                center = pyautogui.center(location)
                pyautogui.click(center)
                print(f"[CLICK] {description}")
                return True
            except Exception as e:
                print(f"[CLICK] Error on attempt {attempt + 1}: {str(e)}")
                if attempt < retries - 1:
                    self.stoppable_sleep(delay)

        print(f"[CLICK] Failed to click {description}")
        return False
