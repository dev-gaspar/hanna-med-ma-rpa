"""
Base Flow - Abstract base class for all RPA flows.
Provides common flow lifecycle and error handling.
"""

from abc import ABC, abstractmethod
from datetime import datetime

import pyautogui
import pydirectinput
import requests

from config import config
from core.rpa_engine import RPABotBase, rpa_state, set_should_stop
from core.system_utils import keep_system_awake, allow_system_sleep
from core.vdi_input import stoppable_sleep, type_with_clipboard, press_key_vdi
from logger import logger
from services.modal_watcher_service import start_modal_watcher, stop_modal_watcher


class BaseFlow(RPABotBase, ABC):
    """
    Abstract base class for hospital-specific RPA flows.
    Provides common lifecycle management and error handling.
    """

    # Override in subclasses
    FLOW_NAME = "base"
    FLOW_TYPE = "base_flow"
    N8N_LIST_WEBHOOK_URL = config.get_rpa_setting("n8n_list_webhook_url")
    N8N_ERROR_WEBHOOK_URL = config.get_rpa_setting("n8n_error_webhook_url")
    N8N_SUMMARY_WEBHOOK_URL = config.get_rpa_setting("n8n_summary_webhook_url")

    def __init__(self):
        super().__init__()
        self.execution_id = None
        self.sender = None
        self.instance = None
        self.trigger_type = None
        self.doctor_name = None
        self.credentials = []  # List of CredentialItem objects

    def setup(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        **kwargs,
    ):
        """
        Setup flow with execution context.
        Subclasses can override to handle additional kwargs (e.g., patient_name).
        """
        self.execution_id = execution_id
        self.sender = sender
        self.instance = instance
        self.trigger_type = trigger_type
        self.doctor_name = doctor_name
        self.credentials = credentials or []

        # Update global state
        rpa_state["execution_id"] = execution_id
        rpa_state["sender"] = sender
        rpa_state["instance"] = instance
        rpa_state["trigger_type"] = trigger_type
        rpa_state["doctor_name"] = doctor_name
        rpa_state["status"] = "running"

    def get_credentials_for_system(self, system_key: str) -> dict:
        """
        Get credentials fields for a specific system from the credentials array.
        Returns the fields dict or raises Exception if not found.
        """
        for cred in self.credentials:
            # Handle both dict and Pydantic model
            if hasattr(cred, "systemKey"):
                key = (
                    cred.systemKey.value
                    if hasattr(cred.systemKey, "value")
                    else cred.systemKey
                )
                fields = cred.fields
            else:
                key = cred.get("systemKey", "")
                fields = cred.get("fields", {})

            if key == system_key:
                return fields

        raise Exception(
            f"Credentials for system '{system_key}' not found in webhook payload"
        )

    def teardown(self):
        """Cleanup after flow execution."""
        rpa_state["status"] = "idle"
        rpa_state["current_step"] = None
        rpa_state["sender"] = None
        rpa_state["instance"] = None
        rpa_state["trigger_type"] = None
        rpa_state["doctor_name"] = None
        set_should_stop(False)
        print("[INFO] RPA status: idle")

    def set_step(self, step_name):
        """Set current step in global state."""
        rpa_state["current_step"] = step_name

    @abstractmethod
    def execute(self):
        """
        Execute the flow-specific steps.
        Must be implemented by subclasses.

        Returns:
            Result data (screenshots, pdf_data, etc.)
        """
        pass

    @abstractmethod
    def notify_completion(self, result):
        """
        Notify n8n of successful completion.
        Must be implemented by subclasses.
        """
        pass

    # Lobby URL for VDI Desktops
    LOBBY_URL = "https://baptist-health-south-florida.workspaceair.com/catalog-portal/ui#/apps/categories/VDI%2520Desktops"

    def verify_lobby(self):
        """
        Verify we are on the lobby screen. If not, navigate to lobby.
        Also dismisses any blocking OK modal if present.
        """
        logger.info("[LOBBY] Verifying lobby screen...")

        # First, check for and dismiss the OK modal if present
        self._dismiss_ok_modal()

        # Check if we're on the lobby screen
        lobby_visible = self._check_lobby_visible()

        if not lobby_visible:
            logger.info("[LOBBY] Not on lobby screen - navigating...")
            self._navigate_to_lobby()

            # Wait and verify we arrived
            stoppable_sleep(5)

            # Check again for OK modal after navigation
            self._dismiss_ok_modal()

            # Final verification
            if not self._check_lobby_visible():
                logger.warning("[LOBBY] Could not verify lobby after navigation")
            else:
                logger.info("[LOBBY] Successfully navigated to lobby")
        else:
            logger.info("[LOBBY] Already on lobby screen")

    def _check_lobby_visible(self):
        """Check if lobby screen is visible."""
        try:
            location = pyautogui.locateOnScreen(
                config.get_rpa_setting("images.lobby"), confidence=self.confidence
            )
            return location is not None
        except pyautogui.ImageNotFoundException:
            return False
        except Exception:
            return False

    def _dismiss_ok_modal(self):
        """Dismiss the OK modal if it appears (click twice with delay)."""
        try:
            ok_modal = pyautogui.locateOnScreen(
                config.get_rpa_setting("images.ok_modal"), confidence=self.confidence
            )
            if ok_modal:
                logger.info("[LOBBY] OK modal detected - dismissing...")
                center = pyautogui.center(ok_modal)
                pyautogui.click(center)
                stoppable_sleep(2)
                pyautogui.click(center)
                stoppable_sleep(1)
                logger.info("[LOBBY] OK modal dismissed")
        except pyautogui.ImageNotFoundException:
            pass
        except Exception as e:
            logger.warning(f"[LOBBY] Error checking OK modal: {e}")

    def _navigate_to_lobby(self):
        """Navigate to the lobby URL using Ctrl+L."""
        # Focus on URL bar with Ctrl+L
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.2)
        pydirectinput.press("l")
        stoppable_sleep(0.2)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(1)

        # Type the lobby URL
        type_with_clipboard(self.LOBBY_URL)
        stoppable_sleep(0.5)

        # Press Enter to navigate
        press_key_vdi("enter")
        logger.info("[LOBBY] Navigating to lobby URL...")

    def run(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        **kwargs,
    ):
        """
        Main entry point - runs the complete flow with error handling.
        Accepts **kwargs for flow-specific parameters (e.g., patient_name).
        """
        logger.info(f"[FLOW] >>> run() started for {self.FLOW_NAME}")
        logger.info(f"[FLOW] kwargs: {kwargs}")

        set_should_stop(False)
        self.setup(
            execution_id,
            sender,
            instance,
            trigger_type,
            doctor_name,
            credentials,
            **kwargs,
        )

        logger.info("=" * 70)
        logger.info(f" STARTING {self.FLOW_NAME.upper()}")
        logger.info("=" * 70)
        logger.info(f"[INFO] Execution ID: {execution_id}")
        logger.info(f"[INFO] Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)

        keep_system_awake()

        # Start modal watcher to handle unexpected modals during flow execution
        start_modal_watcher()

        # Verify we're on the lobby before starting
        self.verify_lobby()

        try:
            result = self.execute()
            self.notify_completion(result)

            print("\n" + "=" * 70)
            print(f" {self.FLOW_NAME.upper()} COMPLETED SUCCESSFULLY")
            print("=" * 70 + "\n")

        except KeyboardInterrupt:
            print(f"\n[STOP] {self.FLOW_NAME} Stopped by User")
            self.notify_error("RPA stopped by user")

        except Exception as e:
            print(f"\n[ERROR] {self.FLOW_NAME} Failed: {e}")
            self.notify_error(str(e))

        finally:
            # Stop modal watcher as flow execution is complete
            stop_modal_watcher()
            allow_system_sleep()
            self.teardown()
            print("[INFO] System ready for new execution\n")

    def notify_error(self, error_message):
        """Notify n8n of an error with screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_url = None

        # Capture and upload error screenshot
        try:
            screenshot_url = self._capture_error_screenshot(timestamp)
            logger.info(f"[ERROR] Screenshot captured and uploaded: {screenshot_url}")
        except Exception as screenshot_error:
            logger.warning(
                f"[ERROR] Failed to capture error screenshot: {screenshot_error}"
            )

        payload = {
            "execution_id": self.execution_id,
            "status": "error",
            "type": self.FLOW_TYPE,
            "error": error_message,
            "failed_step": rpa_state["current_step"],
            "timestamp": timestamp,
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
            "screenshot_url": screenshot_url,
        }
        # Send to dedicated error webhook instead of main webhook
        response = requests.post(self.N8N_ERROR_WEBHOOK_URL, json=payload)
        logger.info(
            f"[N8N] Error notified to {self.N8N_ERROR_WEBHOOK_URL} - Status: {response.status_code}"
        )
        return response

    def _capture_error_screenshot(self, timestamp):
        """Capture screenshot on error and upload to S3."""
        from core.s3_client import get_s3_client

        s3_client = get_s3_client()
        img_buffer = s3_client.take_screenshot()

        # Generate error screenshot filename
        failed_step = rpa_state.get("current_step", "unknown_step")
        filename = (
            f"{self.FLOW_TYPE}/{self.execution_id}/error_{failed_step}_{timestamp}.png"
        )

        s3_client.upload_image(img_buffer, filename)
        screenshot_url = s3_client.generate_presigned_url(filename)

        return screenshot_url

    def _send_to_list_webhook_n8n(self, data):
        """Send data to the n8n list webhook (patient lists)."""
        response = requests.post(self.N8N_LIST_WEBHOOK_URL, json=data)
        return response

    def _send_to_summary_webhook_n8n(self, data):
        """Send data to the n8n summary webhook (patient summaries)."""
        response = requests.post(self.N8N_SUMMARY_WEBHOOK_URL, json=data)
        return response
