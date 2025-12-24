"""
Jackson Batch Summary Flow - Batch patient summary for Jackson Health.

Extends BaseBatchSummaryFlow to provide Jackson-specific implementation.
Keeps EMR session open while processing multiple patients.
"""

import threading
from typing import Optional

import pyautogui
import pyperclip
import pydirectinput

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_batch_summary import BaseBatchSummaryFlow
from .jackson import JacksonFlow
from agentic import AgentRunner
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer


class JacksonBatchSummaryFlow(BaseBatchSummaryFlow):
    """
    Batch summary flow for Jackson Health.

    Keeps the Jackson EMR session open while processing multiple patients,
    returning consolidated results at the end.
    """

    FLOW_NAME = "Jackson Batch Summary"
    FLOW_TYPE = "jackson_batch_summary"

    # Webhook URL for the Jackson Summary brain in n8n (for agentic phase)
    JACKSON_SUMMARY_BRAIN_URL = config.get_rpa_setting(
        "agentic.jackson_summary_brain_url"
    )

    def __init__(self):
        super().__init__()
        self._jackson_flow = JacksonFlow()
        self._omniparser_warmed = False

    def setup(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        patient_names=None,
        hospital_type=None,
        **kwargs,
    ):
        """Setup flow with execution context."""
        super().setup(
            execution_id,
            sender,
            instance,
            trigger_type,
            doctor_name,
            credentials,
            patient_names=patient_names,
            hospital_type=hospital_type,
            **kwargs,
        )
        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )

    def navigate_to_patient_list(self) -> bool:
        """
        Navigate to Jackson patient list.
        Reuses steps 1-8 from the standard Jackson flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH] Navigating to patient list...")

        try:
            # Warmup OmniParser in background while navigating
            warmup_thread = threading.Thread(
                target=self._warmup_omniparser, daemon=True
            )
            warmup_thread.start()

            # Reuse Jackson flow steps
            self._jackson_flow.step_1_tab()
            self._jackson_flow.step_2_powered()
            self._jackson_flow.step_3_open_download()
            self._jackson_flow.step_4_username()
            self._jackson_flow.step_5_password()
            self._jackson_flow.step_6_login_ok()

            # Handle info modal
            self._handle_info_modal_after_login()

            self._jackson_flow.step_7_patient_list()
            self._jackson_flow.step_8_hospital_tab()

            # Wait for warmup
            if warmup_thread.is_alive():
                warmup_thread.join(timeout=60)

            stoppable_sleep(3)
            logger.info("[JACKSON-BATCH] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[JACKSON-BATCH] Navigation failed: {e}")
            return False

    def find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the agentic brain.

        Returns:
            True if patient found, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[JACKSON-BATCH] Finding patient: {patient_name}")

        goal = (
            f"Find and open the Final Report for patient '{patient_name}'. "
            f"Navigate through the patient list, search for the patient name, "
            f"click on their record, and open the Final Report tab. "
            f"Signal 'finish' when the Final Report content is visible. "
            f"Signal 'patient_not_found' if you cannot locate the patient after searching."
        )

        runner = AgentRunner(
            n8n_webhook_url=self.JACKSON_SUMMARY_BRAIN_URL,
            max_steps=30,
            step_delay=1.5,
        )

        result = runner.run(goal=goal)

        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[JACKSON-BATCH] Patient not found: {patient_name}")
            return False

        if result.status != AgentStatus.FINISHED:
            logger.error(f"[JACKSON-BATCH] Agent error: {result.error}")
            return False

        logger.info(f"[JACKSON-BATCH] Patient found in {result.steps_taken} steps")
        stoppable_sleep(2)
        return True

    def extract_content(self) -> str:
        """
        Extract content from the current patient's Final Report.
        Uses Ctrl+A, Ctrl+C to copy content.
        """
        self.set_step("EXTRACT_CONTENT")
        logger.info(f"[JACKSON-BATCH] Extracting content for: {self.current_patient}")

        # Click on report document area
        report_element = self.wait_for_element(
            config.get_rpa_setting("images.jackson_report_document"),
            timeout=10,
            description="Report Document",
        )

        if report_element:
            self.safe_click(report_element, "Report Document")
        else:
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Clear clipboard
        pyperclip.copy("")
        stoppable_sleep(0.3)

        # Select all (Ctrl+A)
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("a")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        # Copy (Ctrl+C)
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("c")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        content = pyperclip.paste()

        if content and len(content) > 50:
            logger.info(f"[JACKSON-BATCH] Extracted {len(content)} characters")
        else:
            logger.warning("[JACKSON-BATCH] Content seems too short")

        return content or ""

    def return_to_patient_list(self):
        """
        Close current patient detail and return to patient list.
        Uses Alt+F4 to close the patient detail view.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH] Returning to patient list...")

        # Click center to ensure focus
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        stoppable_sleep(5)
        logger.info("[JACKSON-BATCH] Back at patient list")

    def cleanup(self):
        """Close Jackson EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[JACKSON-BATCH] Cleanup - closing EMR...")

        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient list/Jackson window with Alt+F4
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        stoppable_sleep(3)

        # Navigate to VDI desktop
        self._jackson_flow.step_11_vdi_tab()

        logger.info("[JACKSON-BATCH] Cleanup complete")

    def _warmup_omniparser(self):
        """Pre-heat OmniParser API."""
        if self._omniparser_warmed:
            return

        try:
            capturer = get_screen_capturer()
            omniparser = get_omniparser_client()
            data_url = capturer.capture_data_url()
            parsed = omniparser.parse_image(data_url)
            logger.info(
                f"[JACKSON-BATCH] OmniParser warmed up - {len(parsed.elements)} elements"
            )
            self._omniparser_warmed = True
        except Exception as e:
            logger.warning(f"[JACKSON-BATCH] Warmup failed: {e}")

    def _handle_info_modal_after_login(self):
        """Handle info modal that may appear after login."""
        info_modal = self.wait_for_element(
            config.get_rpa_setting("images.jackson_info_modal"),
            timeout=3,
            description="Info Modal",
        )

        if info_modal:
            logger.info("[JACKSON-BATCH] Info modal detected - dismissing")
            pydirectinput.press("enter")
            stoppable_sleep(2)
