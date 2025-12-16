"""
Modal Watcher Service - Background thread that monitors and dismisses unexpected modals.

This service handles modals that can appear at any time during flow execution,
such as Jackson's OK modal, without interrupting the main flow logic.
"""

import threading
import time

import pyautogui

from config import config
from logger import logger


class ModalWatcherService:
    """
    Service that monitors for unexpected modals during flow execution.
    Runs in a background thread and automatically dismisses modals when detected.

    Similar to robust_wait_for_element but operates at the flow execution level
    rather than individual step level.
    """

    # Default check interval in seconds
    DEFAULT_CHECK_INTERVAL = 2.0

    def __init__(self, check_interval: float = None):
        """
        Initialize the modal watcher service.

        Args:
            check_interval: How often to check for modals (seconds).
                           Lower = more responsive but higher CPU usage.
        """
        self.check_interval = check_interval or self.DEFAULT_CHECK_INTERVAL
        self._stop_event = threading.Event()
        self._thread = None
        self._confidence = config.get_rpa_setting("confidence", 0.8)

        # Registry of modals to watch for
        # Format: {modal_key: (image_path, handler_func, description)}
        self._modal_handlers = {}

        # Register default modals
        self._register_default_modals()

    def _register_default_modals(self):
        """Register default modal handlers."""
        # Jackson OK Modal
        ok_modal_image = config.get_rpa_setting("images.ok_modal")
        if ok_modal_image:
            self.register_modal(
                key="jackson_ok_modal",
                image_path=ok_modal_image,
                handler=self._dismiss_ok_modal,
                description="Jackson OK Modal",
            )

    def register_modal(
        self, key: str, image_path: str, handler: callable, description: str
    ):
        """
        Register a modal to watch for.

        Args:
            key: Unique identifier for this modal
            image_path: Path to the image used to detect the modal
            handler: Function to call when modal is detected (receives location)
            description: Human-readable description for logging
        """
        self._modal_handlers[key] = (image_path, handler, description)
        logger.debug(f"[MODAL WATCHER] Registered modal: {description}")

    def unregister_modal(self, key: str):
        """Unregister a modal from the watcher."""
        if key in self._modal_handlers:
            del self._modal_handlers[key]
            logger.debug(f"[MODAL WATCHER] Unregistered modal: {key}")

    def _dismiss_ok_modal(self, location):
        """
        Handler for Jackson OK modal - clicks twice with delay.

        Args:
            location: PyAutoGUI location of the modal
        """
        try:
            center = pyautogui.center(location)
            pyautogui.click(center)
            time.sleep(2)
            pyautogui.click(center)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"[MODAL WATCHER] Error dismissing OK modal: {e}")

    def _check_for_modals(self):
        """Check for any registered modals and handle them."""
        for key, (image_path, handler, description) in self._modal_handlers.items():
            try:
                location = pyautogui.locateOnScreen(
                    image_path, confidence=self._confidence
                )
                if location:
                    logger.info(f"[MODAL WATCHER] Detected: {description}")
                    handler(location)
                    logger.info(f"[MODAL WATCHER] Dismissed: {description}")
                    # After handling one modal, restart the loop
                    # to avoid stale state
                    return True
            except pyautogui.ImageNotFoundException:
                continue
            except Exception as e:
                logger.debug(f"[MODAL WATCHER] Error checking {description}: {e}")
        return False

    def _run_watcher(self):
        """Main watcher loop running in background thread."""
        logger.info("[MODAL WATCHER] Service started")
        logger.info(f"[MODAL WATCHER] Check interval: {self.check_interval}s")
        logger.info(f"[MODAL WATCHER] Watching {len(self._modal_handlers)} modal(s)")

        while not self._stop_event.is_set():
            try:
                # Check for modals
                self._check_for_modals()
            except Exception as e:
                logger.debug(f"[MODAL WATCHER] Error in watcher loop: {e}")

            # Wait for the interval or until stopped
            if self._stop_event.wait(self.check_interval):
                break  # Stop event was set

        logger.info("[MODAL WATCHER] Service stopped")

    def start(self):
        """Start the modal watcher service."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[MODAL WATCHER] Service already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_watcher, daemon=True, name="ModalWatcherThread"
        )
        self._thread.start()

    def stop(self):
        """Stop the modal watcher service."""
        if self._thread is None:
            return

        logger.info("[MODAL WATCHER] Stopping service...")
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None

    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._thread is not None and self._thread.is_alive()


# Singleton instance
_modal_watcher = None


def get_modal_watcher(check_interval: float = None) -> ModalWatcherService:
    """Get or create the modal watcher service singleton."""
    global _modal_watcher
    if _modal_watcher is None:
        _modal_watcher = ModalWatcherService(check_interval)
    return _modal_watcher


def start_modal_watcher(check_interval: float = None):
    """Start the modal watcher service."""
    service = get_modal_watcher(check_interval)
    service.start()
    return service


def stop_modal_watcher():
    """Stop the modal watcher service."""
    global _modal_watcher
    if _modal_watcher is not None:
        _modal_watcher.stop()
