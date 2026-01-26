"""
Steward Insurance Flow - RPA + Agentic flow for patient insurance extraction.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Local agentic runner (PatientFinder) to find and click the patient
3. RPA actions to navigate to insurance tab and extract content
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
from .steward import StewardFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async

# Dedicated runner for insurance flow (PatientFinder + click patient)
from agentic.runners import StewardInsuranceRunner


class StewardInsuranceFlow(BaseFlow):
    """
    RPA flow for extracting patient insurance from Steward Health (Meditech).

    Workflow:
    1. Warmup: Pre-heat OmniParser API in background
    2. Phase 1 (RPA): Navigate to patient list using existing Steward flow steps
    3. Phase 2 (Agentic + RPA): Use PatientFinder to locate patient, then click
    4. Phase 3 (RPA): Navigate to Administrative > Demographics > Insurance > General,
                      select all text and copy insurance content
    5. Phase 4 (RPA): Cleanup - close Meditech session and return to start
    """

    FLOW_NAME = "Steward Patient Insurance"
    FLOW_TYPE = "steward_patient_insurance"
    EMR_TYPE = "steward"

    def __init__(self):
        super().__init__()
        self.patient_name: Optional[str] = None
        self.copied_content: Optional[str] = None

        # Reference to Steward flow for reusing navigation steps
        self._steward_flow = StewardFlow()

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

        # Also setup the internal Steward flow reference
        self._steward_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[STEWARD INSURANCE] Patient to find: {patient_name}")

    def execute(self):
        """Execute the flow for patient insurance extraction."""
        if not self.patient_name:
            raise ValueError("Patient name is required for insurance flow")

        # Start OmniParser warmup in background BEFORE Phase 1
        start_warmup_async()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[STEWARD INSURANCE] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[STEWARD INSURANCE] Phase 1: Complete - Patient list visible")

        # Phase 2: Agentic - Find patient and click
        logger.info(
            f"[STEWARD INSURANCE] Phase 2: Finding patient '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open = (
            self._phase2_agentic_find_and_click_patient()
        )

        # Handle patient not found
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[STEWARD INSURANCE] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
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
                f"[STEWARD INSURANCE] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )
            self.notify_error(error_msg)

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

        logger.info("[STEWARD INSURANCE] Phase 2: Complete - Patient clicked")

        # Phase 3: RPA - Navigate to insurance and extract content
        logger.info("[STEWARD INSURANCE] Phase 3: Extracting insurance content...")
        self._phase3_extract_insurance_content()
        logger.info("[STEWARD INSURANCE] Phase 3: Complete - Content extracted")

        # Phase 4: Cleanup
        logger.info("[STEWARD INSURANCE] Phase 4: Cleanup...")
        self._phase4_cleanup()
        logger.info("[STEWARD INSURANCE] Phase 4: Complete")

        logger.info("[STEWARD INSURANCE] Flow complete")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content or "[ERROR] No content extracted",
            "patient_found": True,
        }

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Navigates until step6_load_menu is visible (patient list ready).

        Same as StewardSummaryFlow Phase 1.
        """
        self.set_step("PHASE1_NAVIGATE_TO_PATIENT_LIST")

        # Reuse Steward flow steps to get to patient list visibility
        self._steward_flow.step_1_tab()
        self._steward_flow.step_2_favorite()
        self._steward_flow.step_3_meditech()
        self._steward_flow.step_4_login()
        self._steward_flow.step_5_open_session()
        self._steward_flow.step_6_navigate_menu_5()

        # Wait for step6_load_menu (three lines menu) to be visible
        # Use robust_wait to handle Sign List popup if it appears
        logger.info("[PHASE 1] Waiting for step6_load_menu (patient list visible)...")

        menu = self._steward_flow.robust_wait_for_element(
            config.get_rpa_setting("images.steward_load_menu_6"),
            target_description="Menu (step 6) - Patient list visible",
            handlers=self._steward_flow._get_sign_list_handlers(),
            timeout=config.get_timeout("steward.menu"),
        )

        if not menu:
            raise Exception("step6_load_menu not found - patient list not visible")

        logger.info("[PHASE 1] step6_load_menu visible - Patient list is ready")

        # Give time for the patient list to fully render
        stoppable_sleep(2)

    def _phase2_agentic_find_and_click_patient(self) -> tuple:
        """
        Phase 2: Use StewardInsuranceRunner to find and click patient.

        The runner:
        1. Uses PatientFinderAgent to locate patient with scroll support
        2. Clicks on the patient to open their detail

        Returns:
            Tuple of (status, error_message, patient_detail_open)
        """
        self.set_step("PHASE2_AGENTIC_FIND_AND_CLICK_PATIENT")

        runner = StewardInsuranceRunner(
            max_steps=15,
            step_delay=1.5,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(
                f"[STEWARD INSURANCE] Agent signaled patient not found: {result.error}"
            )
            return ("patient_not_found", result.error, result.patient_detail_open)

        # Check for failures
        if result.status != AgentStatus.FINISHED:
            error_msg = (
                result.error or "Agent did not complete (max steps reached or error)"
            )
            logger.error(f"[STEWARD INSURANCE] Agent failed: {error_msg}")
            return ("error", error_msg, result.patient_detail_open)

        logger.info(
            f"[STEWARD INSURANCE] Agent completed in {result.steps_taken} steps"
        )
        stoppable_sleep(2)
        return ("success", None, True)

    def _phase3_extract_insurance_content(self):
        """
        Phase 3: RPA to navigate to insurance section and extract content.

        Flow:
        1. Click on Administrative tab
        2. Wait and click on Administrative menu item
        3. Click on Demographics
        4. Click on Insurance
        5. Click on General to focus text area
        6. Ctrl+A to select all insurance info
        7. Ctrl+C to copy content
        8. Click on General (selected) to deselect
        """
        self.set_step("PHASE3_EXTRACT_INSURANCE_CONTENT")

        # Step 1: Click Administrative Tab
        logger.info("[PHASE 3] Step 1: Clicking Administrative Tab...")
        tab_admin_img = config.get_rpa_setting(
            "images.steward_insurance_tab_administrative"
        )
        location = self.wait_for_element(
            tab_admin_img,
            timeout=15,
            confidence=0.8,
            description="Administrative Tab",
        )
        if not location:
            raise Exception("Administrative Tab not found")
        self.safe_click(location, "Administrative Tab")
        stoppable_sleep(3)

        # Step 2: Click Administrative menu item
        logger.info("[PHASE 3] Step 2: Clicking Administrative menu item...")
        admin_img = config.get_rpa_setting("images.steward_insurance_administrative")
        location = self.wait_for_element(
            admin_img,
            timeout=15,
            confidence=0.8,
            description="Administrative menu",
        )
        if not location:
            raise Exception("Administrative menu not found")
        self.safe_click(location, "Administrative menu")
        stoppable_sleep(2)

        # Step 3: Click Demographics
        logger.info("[PHASE 3] Step 3: Clicking Demographics...")
        demographics_img = config.get_rpa_setting(
            "images.steward_insurance_demographics"
        )
        location = self.wait_for_element(
            demographics_img,
            timeout=15,
            confidence=0.8,
            description="Demographics",
        )
        if not location:
            raise Exception("Demographics not found")
        self.safe_click(location, "Demographics")
        stoppable_sleep(2)

        # Step 4 & 5: Click Insurance and Verify with General (Retry Logic)
        logger.info("[PHASE 3] Step 4: Clicking Insurance...")
        insurance_img = config.get_rpa_setting("images.steward_insurance_insurance")
        general_img = config.get_rpa_setting("images.steward_insurance_general")

        max_retries = 1
        for attempt in range(max_retries + 1):
            # Click Insurance
            location = self.wait_for_element(
                insurance_img,
                timeout=15,
                confidence=0.8,
                description="Insurance",
            )
            if not location:
                raise Exception("Insurance button not found")
            self.safe_click(location, "Insurance")
            stoppable_sleep(2)

            # Check for General (Verification)
            logger.info(
                f"[PHASE 3] Step 5: Waiting for General (Attempt {attempt+1})..."
            )
            # Generous timeout as requested to avoid false negatives
            location = self.wait_for_element(
                general_img,
                timeout=20,
                confidence=0.8,
                description="General",
            )

            if location:
                # Found it! Click to focus and break loop
                logger.info("[PHASE 3] General tab found, clicking to focus...")
                self.safe_click(location, "General")
                stoppable_sleep(2)
                break
            else:
                if attempt < max_retries:
                    logger.warning(
                        "[PHASE 3] General tab not found, retrying Insurance click..."
                    )
                else:
                    raise Exception("General tab not found after retry")

        # Step 6: Clear clipboard and Select All + Copy
        logger.info("[PHASE 3] Step 6: Selecting all and copying content...")
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

        # Step 7: Click General (selected) to deselect
        logger.info("[PHASE 3] Step 7: Clicking General selected to deselect...")
        general_selected_img = config.get_rpa_setting(
            "images.steward_insurance_general_selected"
        )
        location = self.wait_for_element(
            general_selected_img,
            timeout=10,
            confidence=0.8,
            description="General (selected)",
        )
        if location:
            self.safe_click(location, "General (selected)")
            stoppable_sleep(1)
        else:
            logger.warning("[PHASE 3] General (selected) not found, continuing...")

        logger.info("[PHASE 3] Insurance content extraction complete")

    def _phase4_cleanup(self):
        """
        Phase 4: Close Meditech session and return to start.
        """
        self.set_step("PHASE4_CLEANUP")

        # Use cleanup with patient detail open since we navigated into patient
        self._cleanup_with_patient_detail_open()

        logger.info("[STEWARD INSURANCE] Cleanup complete")

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup Meditech session and return to lobby.
        Uses Steward flow steps 15-19 exactly as in steward.py.
        """
        logger.info("[STEWARD INSURANCE] Cleaning up and returning to lobby...")
        try:
            # Close Meditech (step_15 handles multiple clicks automatically)
            self._steward_flow.step_15_close_meditech()

            # Right click on logged out tab
            self._steward_flow.step_16_tab_logged_out()

            # Close tab final
            self._steward_flow.step_17_close_tab_final()

            # Reset URL to Horizon home
            self._steward_flow.step_18_url()

            # Return to VDI Desktop
            self._steward_flow.step_19_vdi_tab()

            logger.info("[STEWARD INSURANCE] Cleanup completed successfully")

        except Exception as e:
            logger.warning(f"[STEWARD INSURANCE] Cleanup error (continuing): {e}")
            # Try to at least get back to lobby
            self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup when patient detail window is open.
        Same as _cleanup_and_return_to_lobby since step_15 handles multiple windows.
        """
        logger.info("[STEWARD INSURANCE] Cleaning up with patient detail open...")
        try:
            # Close Meditech - step_15 handles multiple clicks automatically
            self._steward_flow.step_15_close_meditech()

            # Right click on logged out tab
            self._steward_flow.step_16_tab_logged_out()

            # Close tab final
            self._steward_flow.step_17_close_tab_final()

            # Reset URL to Horizon home
            self._steward_flow.step_18_url()

            # Return to VDI Desktop
            self._steward_flow.step_19_vdi_tab()

            logger.info(
                "[STEWARD INSURANCE] Cleanup (patient open) completed successfully"
            )

        except Exception as e:
            logger.warning(f"[STEWARD INSURANCE] Cleanup error (continuing): {e}")
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
