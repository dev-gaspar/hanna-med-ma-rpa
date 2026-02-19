"""
Jackson Insurance Flow - RPA + Agentic flow for patient insurance extraction.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Local agentic runner (PatientFinder) to find and clicked the patient
3. Mocked logic for insurance extraction (Phase 3)
4. Cleanup and return to lobby
"""

from datetime import datetime
from typing import Optional

import pydirectinput
import pyperclip

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_flow import BaseFlow
from .jackson import JacksonFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async

# Dedicated runner for insurance flow (PatientFinder + click patient)
from agentic.runners import JacksonInsuranceRunner


class JacksonInsuranceFlow(BaseFlow):
    """
    RPA flow for extracting patient insurance from Jackson Health.

    Workflow:
    1. Warmup: Pre-heat OmniParser API in background
    2. Phase 1 (RPA): Navigate to patient list using existing Jackson flow steps
    3. Phase 2 (Agentic + RPA): Use PatientFinder to locate patient, then click
    4. Phase 3 (RPA): Extract insurance content (More > Insurance > Guarantors)
    5. Phase 4 (RPA): Cleanup - close Jackson session and return to start
    """

    FLOW_NAME = "Jackson Patient Insurance"
    FLOW_TYPE = "jackson_patient_insurance"
    EMR_TYPE = "jackson"

    def __init__(self):
        super().__init__()
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

        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[JACKSON INSURANCE] Patient to find: {patient_name}")

    def execute(self):
        """Execute the flow for patient insurance extraction."""
        if not self.patient_name:
            raise ValueError("Patient name is required for insurance flow")

        # Start OmniParser warmup in background BEFORE Phase 1
        start_warmup_async()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[JACKSON INSURANCE] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[JACKSON INSURANCE] Phase 1: Complete - Patient list visible")

        # Enter fullscreen for better agentic vision
        logger.info("[JACKSON INSURANCE] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Agentic - Find patient and click
        logger.info(
            f"[JACKSON INSURANCE] Phase 2: Finding patient '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open = (
            self._phase2_agentic_find_and_click_patient()
        )

        # Handle patient not found
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[JACKSON INSURANCE] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
            # Exit fullscreen before cleanup
            self._click_normalscreen()
            self._cleanup_and_return_to_lobby()

            # Notify webhook that patient was not found
            result = {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "error": f"Patient '{self.patient_name}' not found in patient list",
            }
            self.notify_completion(result)
            return result

        # Handle agent error
        if phase2_status == "error":
            error_msg = f"Agent failed: {phase2_error}"
            logger.error(
                f"[JACKSON INSURANCE] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )
            self.notify_error(error_msg)

            # Exit fullscreen before cleanup
            self._click_normalscreen()

            if patient_detail_open:
                self._cleanup_with_patient_detail_open()
            else:
                self._cleanup_and_return_to_lobby()

            return {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "error": error_msg,
            }

        logger.info("[JACKSON INSURANCE] Phase 2: Complete - Patient clicked")

        # Phase 3: Insurance Extraction
        logger.info("[JACKSON INSURANCE] Phase 3: Extracting insurance content...")
        self._phase3_extract_insurance_content()
        logger.info("[JACKSON INSURANCE] Phase 3: Complete - Content extracted")

        # Exit fullscreen before cleanup
        logger.info("[JACKSON INSURANCE] Exiting fullscreen mode...")
        self._click_normalscreen()
        stoppable_sleep(2)

        # Phase 4: Cleanup
        logger.info("[JACKSON INSURANCE] Phase 4: Cleanup...")
        self._phase4_cleanup()
        logger.info("[JACKSON INSURANCE] Phase 4: Complete")

        logger.info("[JACKSON INSURANCE] Flow complete")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content or "[ERROR] No content extracted",
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

    def _handle_info_modal_after_login(self):
        """
        Handle info modal that may appear after Jackson login.
        If detected, press Enter to dismiss it.
        """
        logger.info("[JACKSON INSURANCE] Checking for info modal after login...")

        # Quick check for the info modal (short timeout since it may not appear)
        info_modal = self.wait_for_element(
            config.get_rpa_setting("images.jackson_info_modal"),
            timeout=3,
            description="Info Modal",
        )

        if info_modal:
            logger.info(
                "[JACKSON INSURANCE] Info modal detected - pressing Enter to dismiss"
            )
            pydirectinput.press("enter")
            stoppable_sleep(2)
        else:
            logger.info("[JACKSON INSURANCE] No info modal detected, continuing...")

    def _phase2_agentic_find_and_click_patient(self) -> tuple:
        """
        Phase 2: Use JacksonInsuranceRunner to find and click patient.

        Returns:
            Tuple of (status, error_message, patient_detail_open)
        """
        self.set_step("PHASE2_AGENTIC_FIND_AND_CLICK_PATIENT")

        runner = JacksonInsuranceRunner(
            max_steps=15,
            step_delay=1.5,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(
                f"[JACKSON INSURANCE] Agent signaled patient not found: {result.error}"
            )
            return ("patient_not_found", result.error, result.patient_detail_open)

        # Check for failures
        if result.status != AgentStatus.FINISHED:
            error_msg = (
                result.error or "Agent did not complete (max steps reached or error)"
            )
            logger.error(f"[JACKSON INSURANCE] Agent failed: {error_msg}")
            return ("error", error_msg, result.patient_detail_open)

        logger.info(
            f"[JACKSON INSURANCE] Agent completed in {result.steps_taken} steps"
        )
        stoppable_sleep(2)
        return ("success", None, True)

    def _phase3_extract_insurance_content(self):
        """
        Phase 3: Extract insurance content.

        Flow:
        1. Click 'More' button
        2. Click 'Insurance Information'
        3. Wait for 'Guarantors' tab to be visible
        4. Click 'Guarantors' tab
        5. Ctrl+A -> Ctrl+C
        6. Alt+F4 to close insurance window
        """
        self.set_step("PHASE3_EXTRACT_INSURANCE_CONTENT")

        # Step 1: Click More
        logger.info("[PHASE 3] Step 1: Clicking 'More' button...")
        more_img = config.get_rpa_setting("images.jackson_more")
        location = self.wait_for_element(
            more_img,
            timeout=10,
            confidence=0.8,
            description="More button",
        )
        # Fallback: try alternate image (normal mode vs fullscreen renders differently)
        if not location:
            more_alt_img = config.get_rpa_setting("images.jackson_more_alt")
            if more_alt_img:
                logger.info("[PHASE 3] Trying alternate 'More' button image...")
                location = self.wait_for_element(
                    more_alt_img,
                    timeout=10,
                    confidence=0.8,
                    description="More button (alt)",
                )
        if not location:
            raise Exception("More button not found")
        self.safe_click(location, "More button")
        stoppable_sleep(2)

        # Step 2: Click Insurance Information
        logger.info("[PHASE 3] Step 2: Clicking 'Insurance Information'...")
        insurance_info_img = config.get_rpa_setting(
            "images.jackson_insurance_information"
        )
        location = self.wait_for_element(
            insurance_info_img,
            timeout=10,
            confidence=0.8,
            description="Insurance Information",
        )
        # Fallback: try alternate image (normal mode vs fullscreen)
        if not location:
            ins_alt_img = config.get_rpa_setting(
                "images.jackson_insurance_information_alt"
            )
            if ins_alt_img:
                logger.info(
                    "[PHASE 3] Trying alternate 'Insurance Information' image..."
                )
                location = self.wait_for_element(
                    ins_alt_img,
                    timeout=10,
                    confidence=0.8,
                    description="Insurance Information (alt)",
                )
        if not location:
            raise Exception("Insurance Information not found")
        self.safe_click(location, "Insurance Information")
        stoppable_sleep(4)

        # Step 3 & 4: Wait for and Click Guarantors
        logger.info("[PHASE 3] Step 3: Waiting for 'Guarantors' tab...")
        guarantors_img = config.get_rpa_setting("images.jackson_insurance_guarantors")
        location = self.wait_for_element(
            guarantors_img,
            timeout=15,
            confidence=0.8,
            description="Guarantors tab",
        )
        # Fallback: try alternate image (normal mode vs fullscreen)
        if not location:
            guar_alt_img = config.get_rpa_setting(
                "images.jackson_insurance_guarantors_alt"
            )
            if guar_alt_img:
                logger.info("[PHASE 3] Trying alternate 'Guarantors' image...")
                location = self.wait_for_element(
                    guar_alt_img,
                    timeout=10,
                    confidence=0.8,
                    description="Guarantors tab (alt)",
                )
        if not location:
            raise Exception("Guarantors tab not found")

        logger.info("[PHASE 3] Step 4: Clicking 'Guarantors' tab...")
        self.safe_click(location, "Guarantors tab")
        stoppable_sleep(2)

        # Step 5: Select All and Copy
        logger.info("[PHASE 3] Step 5: Selecting all and copying content...")
        pyperclip.copy("")
        stoppable_sleep(0.3)

        # Ctrl+A to select all
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("a")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        # Ctrl+C to copy
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("c")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(0.5)

        # Get copied content
        self.copied_content = pyperclip.paste()
        logger.info(f"[PHASE 3] Copied {len(self.copied_content)} characters")

        # Step 6: Close insurance window (Alt+F4)
        logger.info("[PHASE 3] Step 6: Closing insurance window (Alt+F4)...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")
        stoppable_sleep(2)

        logger.info("[PHASE 3] Insurance extraction complete")

    def _phase4_cleanup(self):
        """
        Phase 4: Close Jackson session and return to start.
        """
        self.set_step("PHASE4_CLEANUP")

        # Use cleanup with patient detail open since we navigated into patient
        # Note: Phase 3 performs one Alt+F4 to close the insurance window.
        # We assume we are back at the patient detail view, so we use the standard
        # cleanup which closes the detail view and then the list.
        self._cleanup_with_patient_detail_open()

        logger.info("[JACKSON INSURANCE] Cleanup complete")

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup Jackson EMR session and return to lobby when patient not found.
        Only performs one close action since no patient detail was opened.
        """
        logger.info("[JACKSON INSURANCE] Performing cleanup (patient list only)...")
        try:
            # Click on screen center to ensure window has focus
            # (Assuming standard resolution or full screen, using center is safe)
            # Reusing logic from summary flow, but abstracting direct pyautogui where possible in BaseFlow could be better
            # For now keeping consistent with summary flow structure
            import pyautogui

            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # Only one close needed: Close the patient list/Jackson main window with Alt+F4
            logger.info("[JACKSON INSURANCE] Sending Alt+F4 to close Jackson...")
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
            logger.warning(f"[JACKSON INSURANCE] Cleanup error (continuing): {e}")

        # Verify we're back at the lobby
        self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup Jackson EMR session when patient detail is open.
        Performs TWO close actions: first patient detail, then patient list.
        Uses visual validation to confirm we're at patient list before second close.
        """
        logger.info("[JACKSON INSURANCE] Performing cleanup (patient detail + list)...")
        try:
            import pyautogui

            screen_w, screen_h = pyautogui.size()
            patient_list_header_img = config.get_rpa_setting(
                "images.jackson_patient_list_header"
            )

            # Click on screen center to ensure window has focus
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # First close: Close the patient detail view with Alt+F4
            logger.info("[JACKSON INSURANCE] Sending Alt+F4 to close patient detail...")
            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            # Wait 15 seconds for the system to process the close
            # PowerChart can freeze during close - longer wait prevents Alt+F4 accumulation
            logger.info(
                "[JACKSON INSURANCE] Waiting 15s for system to process close..."
            )
            stoppable_sleep(15)

            # Use patient wait with multiple attempts (NO additional Alt+F4)
            header_found = self._wait_for_patient_list_with_patience(
                patient_list_header_img,
                max_attempts=3,
                attempt_timeout=15,
            )

            if header_found:
                logger.info("[JACKSON INSURANCE] OK - Patient list confirmed")
            else:
                # Log warning but do NOT send another Alt+F4
                logger.warning(
                    "[JACKSON INSURANCE] Patient list header not detected after patience wait. "
                    "Continuing anyway to avoid race condition."
                )

            # Click on screen center to focus the patient list window
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # Second close: Close the patient list/Jackson main window with Alt+F4
            logger.info("[JACKSON INSURANCE] Sending Alt+F4 to close Jackson list...")
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
            logger.warning(f"[JACKSON INSURANCE] Cleanup error (continuing): {e}")

        # Verify we're back at the lobby
        self.verify_lobby()

    def notify_completion(self, result):
        """Notify n8n of completion with the insurance content."""
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
        # Send to dedicated insurance webhook
        response = self._send_to_insurance_webhook_n8n(payload)
        logger.info(
            f"[N8N] Insurance notification sent - Status: {response.status_code}"
        )
        return response
