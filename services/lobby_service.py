"""
Lobby Verification Service - Periodically verifies the RPA is on the lobby screen.
"""

import threading
import time

from config import config
from logger import logger


class LobbyVerificationService:
    """
    Service that periodically verifies the RPA is on the lobby screen.
    Runs in a background thread and checks every configured interval.
    """

    def __init__(self, interval_seconds=3600):  # Default: 1 hour
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = None
        self._verifier = None

    def _get_verifier(self):
        """Lazy load the verifier to avoid circular imports."""
        if self._verifier is None:
            from flows.base_flow import BaseFlow
            from core.rpa_engine import rpa_state

            # Create a minimal verifier instance
            class LobbyVerifier(BaseFlow):
                FLOW_NAME = "LobbyVerifier"
                FLOW_TYPE = "lobby_verification"

                def execute(self):
                    pass

                def notify_completion(self, result):
                    pass

            self._verifier = LobbyVerifier()
        return self._verifier

    def _run_verification(self):
        """Run lobby verification in a loop."""
        logger.info("[LOBBY SERVICE] Background verification service started")
        logger.info(
            f"[LOBBY SERVICE] Interval: {self.interval_seconds} seconds ({self.interval_seconds / 3600:.1f} hours)"
        )

        while not self._stop_event.is_set():
            # Wait for the interval or until stopped
            if self._stop_event.wait(self.interval_seconds):
                break  # Stop event was set

            # Check if RPA is idle before running verification
            from core.rpa_engine import rpa_state

            if rpa_state.get("status") == "running":
                logger.info(
                    "[LOBBY SERVICE] RPA is busy, skipping periodic verification"
                )
                continue

            try:
                logger.info("[LOBBY SERVICE] Running periodic lobby verification...")
                verifier = self._get_verifier()
                verifier.verify_lobby()
                logger.info("[LOBBY SERVICE] Periodic verification complete")
            except Exception as e:
                logger.error(f"[LOBBY SERVICE] Verification failed: {e}")

    def start(self):
        """Start the background verification service."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[LOBBY SERVICE] Service already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_verification, daemon=True)
        self._thread.start()
        logger.info("[LOBBY SERVICE] Service started")

    def stop(self):
        """Stop the background verification service."""
        if self._thread is None:
            return

        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None
        logger.info("[LOBBY SERVICE] Service stopped")

    def is_running(self):
        """Check if the service is running."""
        return self._thread is not None and self._thread.is_alive()


# Singleton instance
_lobby_service = None


def get_lobby_service(interval_seconds=3600):
    """Get or create the lobby verification service singleton."""
    global _lobby_service
    if _lobby_service is None:
        _lobby_service = LobbyVerificationService(interval_seconds)
    return _lobby_service


def start_lobby_service(interval_seconds=3600):
    """Start the lobby verification service."""
    service = get_lobby_service(interval_seconds)
    service.start()
    return service


def stop_lobby_service():
    """Stop the lobby verification service."""
    global _lobby_service
    if _lobby_service is not None:
        _lobby_service.stop()
