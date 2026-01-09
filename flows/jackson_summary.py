"""
Jackson Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Agentic brain (n8n) to find the specific patient's Final Report
3. Traditional RPA to copy content and close everything
"""

from datetime import datetime
from typing import Optional

import pyautogui
import pyperclip
import pydirectinput
import requests

from config import config
from core.s3_client import get_s3_client
from core.vdi_input import stoppable_sleep, type_with_clipboard
from logger import logger

from .base_flow import BaseFlow
from .jackson import JacksonFlow

# OLD: n8n-based AgentRunner (commented for reference)
# from agentic import AgentRunner
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async

# NEW: Local runner with prompt chaining
from agentic.runners import JacksonSummaryRunner


class JacksonSummaryFlow(BaseFlow):
    """
    Hybrid RPA flow for retrieving patient summary from Jackson Health.

    Workflow:
    1. Phase 1 (RPA): Navigate to patient list using existing Jackson flow steps
    2. Warmup: Pre-heat OmniParser API for faster agentic execution
    3. Phase 2 (Agentic): Use n8n brain to find and open patient's Final Report
    4. Phase 3 (RPA): Copy content, send to n8n for formatting, close everything
    """

    FLOW_NAME = "Jackson Patient Summary"
    FLOW_TYPE = "jackson_patient_summary"

    # Webhook URL for the Jackson Summary brain in n8n (for agentic phase)
    JACKSON_SUMMARY_BRAIN_URL = config.get_rpa_setting(
        "agentic.jackson_summary_brain_url"
    )

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()
        self.patient_name: Optional[str] = None
        self.copied_content: Optional[str] = None

        # Reference to Jackson flow for reusing navigation steps
        self._jackson_flow = JacksonFlow()

    def setup(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        patient_name=None,
        doctor_specialty=None,
        **kwargs,
    ):
        """Setup flow with execution context including patient name."""
        super().setup(
            execution_id,
            sender,
            instance,
            trigger_type,
            doctor_name,
            credentials,
            **kwargs,
        )
        self.patient_name = patient_name
        self.doctor_specialty = doctor_specialty

        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[JACKSON SUMMARY] Patient to find: {patient_name}")
        if doctor_specialty:
            logger.info(f"[JACKSON SUMMARY] Doctor specialty: {doctor_specialty}")

    def execute(self):
        """Execute the hybrid flow for patient summary retrieval."""
        if not self.patient_name:
            raise ValueError("Patient name is required for summary flow")

        # Start OmniParser warmup in background (runs in parallel with Phase 1)
        start_warmup_async()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[JACKSON SUMMARY] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[JACKSON SUMMARY] Phase 1: Complete - Patient list visible")

        # Click fullscreen for better visualization
        logger.info("[JACKSON SUMMARY] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Agentic - Find the patient's Final Report
        logger.info(
            f"[JACKSON SUMMARY] Phase 2: Starting agentic search for '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open = (
            self._phase2_agentic_find_report()
        )

        # Handle patient not found (detail NOT open - only patient list)
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[JACKSON SUMMARY] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
            # Exit fullscreen before cleanup
            self._click_normalscreen()
            # Only patient list open, use simple cleanup (1 Alt+F4)
            self._cleanup_and_return_to_lobby()
            return {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "error": f"Patient '{self.patient_name}' not found in patient list",
            }

        # Handle agent error (failed or ran out of steps)
        if phase2_status == "error":
            error_msg = f"Agent failed: {phase2_error}"
            logger.error(
                f"[JACKSON SUMMARY] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )

            # Notify error to centralized n8n webhook
            self.notify_error(error_msg)

            # Exit fullscreen before cleanup
            self._click_normalscreen()

            # Choose cleanup based on whether patient detail is open
            if patient_detail_open:
                # Patient detail IS open, need 2 Alt+F4 (detail + list)
                self._cleanup_with_patient_detail_open()
            else:
                # Only patient list open, use simple cleanup (1 Alt+F4)
                self._cleanup_and_return_to_lobby()

            return {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "error": error_msg,
            }

        logger.info("[JACKSON SUMMARY] Phase 2: Complete - Report found")

        # Exit fullscreen before copying content
        logger.info("[JACKSON SUMMARY] Exiting fullscreen mode...")
        self._click_normalscreen()

        # Wait for screen to settle
        logger.info("[JACKSON SUMMARY] Waiting for screen to settle...")
        stoppable_sleep(5)

        # Phase 3: Traditional RPA - Click report, copy content and close
        logger.info("[JACKSON SUMMARY] Phase 3a: Clicking on report document...")
        self._phase3_click_report_document()

        logger.info("[JACKSON SUMMARY] Phase 3b: Copying content...")
        self._phase3_copy_content()

        logger.info("[JACKSON SUMMARY] Phase 3c: Closing EMR...")
        self._phase3_close_and_cleanup()

        logger.info("[JACKSON SUMMARY] Complete - Content ready")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content,
            "patient_found": True,
        }

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Reuses steps 1-8 from the standard Jackson flow.
        """
        self.set_step("PHASE1_NAVIGATE_TO_PATIENT_LIST")

        # Reuse Jackson flow steps to get to patient list
        self._jackson_flow.step_1_tab()
        self._jackson_flow.step_2_powered()
        self._jackson_flow.step_3_open_download()
        self._jackson_flow.step_4_username()
        self._jackson_flow.step_5_password()
        self._jackson_flow.step_6_login_ok()

        # Handle info modal that may appear after login (press Enter to dismiss)
        self._handle_info_modal_after_login()

        self._jackson_flow.step_7_patient_list()
        self._jackson_flow.step_8_hospital_tab()

        # Give time for the patient list to fully load
        stoppable_sleep(3)

    def _click_fullscreen(self):
        """Click fullscreen button for better visualization during agentic phase."""
        self.set_step("CLICK_FULLSCREEN")
        fullscreen_img = config.get_rpa_setting("images.jackson_fullscreen_btn")
        try:
            location = pyautogui.locateOnScreen(fullscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[JACKSON SUMMARY] Clicked fullscreen button")
                stoppable_sleep(1)
            else:
                logger.warning(
                    "[JACKSON SUMMARY] Fullscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[JACKSON SUMMARY] Error clicking fullscreen: {e}")

    def _click_normalscreen(self):
        """Click normalscreen button to restore view after agentic phase."""
        self.set_step("CLICK_NORMALSCREEN")
        normalscreen_img = config.get_rpa_setting("images.jackson_normalscreen_btn")
        try:
            location = pyautogui.locateOnScreen(normalscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[JACKSON SUMMARY] Clicked normalscreen button")
                stoppable_sleep(1)
            else:
                logger.warning(
                    "[JACKSON SUMMARY] Normalscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[JACKSON SUMMARY] Error clicking normalscreen: {e}")

    def _phase2_agentic_find_report(self) -> tuple:
        """
        Phase 2: Use local agentic runner to find and open the patient's Final Report.
        Uses prompt chaining with specialized agents (PatientFinder, ReportFinder).

        Returns:
            Tuple of (status, error_message, patient_detail_open):
            - ("success", None, True) if patient found and report opened
            - ("patient_not_found", error_msg, False) if patient not in list
            - ("error", error_msg, bool) if agent failed or ran out of steps
        """
        self.set_step("PHASE2_AGENTIC_FIND_REPORT")

        # =====================================================================
        # NEW: Local runner with prompt chaining (PatientFinder + ReportFinder)
        # =====================================================================
        runner = JacksonSummaryRunner(
            max_steps=30,
            step_delay=1,
            doctor_specialty=self.doctor_specialty,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(
                f"[JACKSON SUMMARY] Agent signaled patient not found: {result.error}"
            )
            return ("patient_not_found", result.error, result.patient_detail_open)

        # Check for other failures (error, stopped, max steps reached)
        if result.status != AgentStatus.FINISHED:
            error_msg = (
                result.error
                or "Agent did not find the report (max steps reached or error)"
            )
            logger.error(f"[JACKSON SUMMARY] Agent failed: {error_msg}")
            return ("error", error_msg, result.patient_detail_open)

        logger.info(f"[JACKSON SUMMARY] Agent completed in {result.steps_taken} steps")

        # Give time for the report content to fully render
        stoppable_sleep(2)
        return ("success", None, True)

        # =====================================================================
        # OLD: n8n-based AgentRunner (commented for reference)
        # =====================================================================
        # goal = (
        #     f"Find and open the Final Report for patient '{self.patient_name}'. "
        #     f"Navigate through the patient list, search for the patient name, "
        #     f"click on their record, and open the Final Report tab. "
        #     f"Signal 'finish' when the Final Report content is visible. "
        #     f"Signal 'patient_not_found' if you cannot locate the patient after searching."
        # )
        #
        # runner = AgentRunner(
        #     n8n_webhook_url=self.JACKSON_SUMMARY_BRAIN_URL,
        #     max_steps=30,
        #     step_delay=1.5,
        # )
        #
        # result = runner.run(goal=goal)
        #
        # if result.status == AgentStatus.PATIENT_NOT_FOUND:
        #     logger.warning(f"[JACKSON SUMMARY] Agent signaled patient not found: {result.error}")
        #     return False
        #
        # if result.status != AgentStatus.FINISHED:
        #     raise Exception(f"Agentic phase failed: {result.error or 'Agent did not find the report'}")
        #
        # logger.info(f"[JACKSON SUMMARY] Agent completed in {result.steps_taken} steps")
        # stoppable_sleep(2)
        # return True

    def _handle_info_modal_after_login(self):
        """
        Handle info modal that may appear after Jackson login.
        If detected, press Enter to dismiss it.
        """
        logger.info("[JACKSON SUMMARY] Checking for info modal after login...")

        # Quick check for the info modal (short timeout since it may not appear)
        info_modal = self.wait_for_element(
            config.get_rpa_setting("images.jackson_info_modal"),
            timeout=3,
            description="Info Modal",
        )

        if info_modal:
            logger.info(
                "[JACKSON SUMMARY] Info modal detected - pressing Enter to dismiss"
            )
            pydirectinput.press("enter")
            stoppable_sleep(2)
        else:
            logger.info("[JACKSON SUMMARY] No info modal detected, continuing...")

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup Jackson EMR session and return to lobby when patient not found.
        Only performs one close action since no patient detail was opened.
        Used when: Patient not found in the list (Phase 2 - PatientFinder failed)
        """
        logger.info("[JACKSON SUMMARY] Performing cleanup (patient list only)...")
        try:
            # Click on screen center to ensure window has focus
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # Only one close needed: Close the patient list/Jackson main window with Alt+F4
            logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close Jackson...")
            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            # Wait for the window to close
            stoppable_sleep(3)

            # Navigate to VDI desktop
            self._jackson_flow.step_11_vdi_tab()

        except Exception as e:
            logger.warning(f"[JACKSON SUMMARY] Cleanup error (continuing): {e}")

        # Verify we're back at the lobby
        self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup Jackson EMR session when patient detail is open.
        Performs TWO close actions: first patient detail, then patient list.
        Used when: Agent failed during ReportFinder phase (patient detail already open)
        """
        logger.info("[JACKSON SUMMARY] Performing cleanup (patient detail + list)...")
        try:
            screen_w, screen_h = pyautogui.size()

            # Click on screen center to ensure window has focus
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # First close: Close the patient detail view with Alt+F4
            logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close patient detail...")
            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            # Wait for the window to close
            stoppable_sleep(5)

            # Click on screen center again to focus the next window
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # Second close: Close the patient list/Jackson main window with Alt+F4
            logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close Jackson list...")
            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            # Wait for the window to close
            stoppable_sleep(3)

            # Navigate to VDI desktop
            self._jackson_flow.step_11_vdi_tab()

        except Exception as e:
            logger.warning(f"[JACKSON SUMMARY] Cleanup error (continuing): {e}")

        # Verify we're back at the lobby
        self.verify_lobby()

    def _phase3_click_report_document(self):
        """
        Phase 3a: Click on the report document area to focus it for copying.
        The agent finished on the document view, we need to click on the document area.
        """
        self.set_step("PHASE3_CLICK_REPORT_DOCUMENT")
        logger.info("[JACKSON SUMMARY] Clicking on report document area...")

        # Try to find and click the report document image
        report_element = self.wait_for_element(
            config.get_rpa_setting("images.jackson_report_document"),
            timeout=10,
            description="Report Document",
        )

        if report_element:
            if not self.safe_click(report_element, "Report Document"):
                logger.warning(
                    "[JACKSON SUMMARY] Could not click report document, trying center screen"
                )
                # Fallback: click center of screen
                screen_w, screen_h = pyautogui.size()
                pyautogui.click(screen_w // 2, screen_h // 2)
        else:
            logger.warning(
                "[JACKSON SUMMARY] Report document image not found, clicking center"
            )
            # Fallback: click center of screen to focus document
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)

        stoppable_sleep(0.5)

    def _phase3_copy_content(self):
        """
        Phase 3b: Copy the content of the Final Report using keyboard shortcuts.
        """
        self.set_step("PHASE3_COPY_CONTENT")
        logger.info("[JACKSON SUMMARY] Copying report content...")

        # Clear clipboard first
        pyperclip.copy("")
        stoppable_sleep(0.3)

        # Select all content with Ctrl+A
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("a")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        # Copy with Ctrl+C
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("c")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        # Get the copied content
        self.copied_content = pyperclip.paste()

        if not self.copied_content or len(self.copied_content) < 50:
            logger.warning("[JACKSON SUMMARY] Copied content seems too short or empty")
        else:
            logger.info(
                f"[JACKSON SUMMARY] Copied {len(self.copied_content)} characters"
            )

    def _phase3_close_and_cleanup(self):
        """
        Phase 3c: Close Cerner patient detail and patient list windows, then return to VDI.

        Flow:
        1. Close patient detail view (first close click)
        2. Check if patient list is visible, if so close it too
        3. Navigate to VDI tab
        """
        self.set_step("PHASE3_CLOSE_AND_CLEANUP")
        logger.info("[JACKSON SUMMARY] Closing patient detail...")

        # Click on screen center to ensure window has focus
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # First close: Close the patient detail view with Alt+F4
        logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for the window to close
        stoppable_sleep(5)

        # Click on screen center again to focus the next window
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Second close: Close the patient list/Jackson main window with Alt+F4
        logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close Jackson...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for the window to close
        stoppable_sleep(3)

        # Navigate to VDI desktop
        self._jackson_flow.step_11_vdi_tab()

    def notify_completion(self, result):
        """Notify n8n of completion with the copied content or patient-not-found status."""
        patient_found = result.get("patient_found", True)
        payload = {
            "execution_id": self.execution_id,
            "status": "completed" if patient_found else "patient_not_found",
            "type": self.FLOW_TYPE,
            "patient_name": result.get("patient_name"),
            "content": result.get("content"),
            "patient_found": patient_found,
            "error": result.get("error"),
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
        }
        # Send to dedicated summary webhook using base method
        response = self._send_to_summary_webhook_n8n(payload)
        logger.info(f"[N8N] Summary notification sent - Status: {response.status_code}")
        return response
