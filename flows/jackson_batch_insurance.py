"""
Jackson Batch Insurance Flow - Batch patient insurance extraction for Jackson Health.

Processes multiple patients in a single EMR session, extracting insurance
information from the Guarantors tab via More > Insurance Information.
Uses JacksonInsuranceRunner for patient finding.
"""

from datetime import datetime
from typing import List, Optional

import pyautogui
import pydirectinput
import pyperclip

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_flow import BaseFlow
from .jackson import JacksonFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import JacksonInsuranceRunner


class JacksonBatchInsuranceFlow(BaseFlow):
    """
    Batch insurance flow for Jackson Health.

    Keeps the Jackson EMR session open in FULLSCREEN mode while processing
    multiple patients, extracting insurance content from Guarantors tab,
    returning consolidated results.

    Flow:
    1. Navigate to patient list
    2. Enter fullscreen mode (better for agentic vision)
    3. For each patient:
       - Find patient and open patient detail (agentic)
       - Click More > Insurance Information > Guarantors
       - Ctrl+A, Ctrl+C to copy content
       - Alt+F4 to close insurance window
       - Alt+F4 to close patient detail (wait for patient list header)
    4. Exit fullscreen mode
    5. Cleanup (close EMR, return to VDI)
    """

    FLOW_NAME = "Jackson Batch Insurance"
    FLOW_TYPE = "jackson_batch_insurance"
    EMR_TYPE = "jackson"

    def __init__(self):
        super().__init__()
        self._jackson_flow = JacksonFlow()
        self._patient_detail_open = False
        self.patient_names: List[str] = []
        self.hospital_type: str = ""
        self.current_patient: Optional[str] = None
        self.current_content: Optional[str] = None
        self.results: List[dict] = []

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
            **kwargs,
        )
        self.patient_names = patient_names or []
        self.hospital_type = hospital_type or "JACKSON"
        self.results = []

        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )

        logger.info(f"[JACKSON-BATCH-INS] Setup for {len(self.patient_names)} patients")

    def execute(self):
        """
        Execute batch insurance extraction.

        1. Navigate to patient list (once)
        2. Enter fullscreen mode
        3. For each patient: find, extract insurance, return to list
        4. Exit fullscreen mode (only at the end)
        5. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" JACKSON BATCH INSURANCE - STARTING")
        logger.info("=" * 70)
        logger.info(f"[JACKSON-BATCH-INS] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self._navigate_to_patient_list():
            logger.error("[JACKSON-BATCH-INS] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Enter fullscreen mode for better agentic vision
        logger.info("[JACKSON-BATCH-INS] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Process each patient in fullscreen mode
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            self.current_patient = patient
            self.current_content = None

            logger.info(
                f"[JACKSON-BATCH-INS] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self._find_patient(patient)

                if found:
                    # Extract insurance content
                    self.current_content = self._extract_insurance()
                    logger.info(
                        f"[JACKSON-BATCH-INS] Extracted insurance for {patient}"
                    )

                    # Return to patient list
                    self._return_to_patient_list()
                else:
                    logger.warning(f"[JACKSON-BATCH-INS] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(
                    f"[JACKSON-BATCH-INS] Error processing {patient}: {str(e)}"
                )
                self.results.append(
                    {
                        "patient": patient,
                        "found": False,
                        "content": None,
                        "error": str(e),
                    }
                )
                # Try to recover by closing patient detail if open
                if self._patient_detail_open:
                    self._close_patient_detail()

        # Exit fullscreen before cleanup
        logger.info("[JACKSON-BATCH-INS] Exiting fullscreen mode...")
        self._click_normalscreen()
        stoppable_sleep(3)

        # Phase 3: Cleanup
        logger.info("[JACKSON-BATCH-INS] Cleanup phase")
        self._cleanup()

        logger.info("=" * 70)
        logger.info(" JACKSON BATCH INSURANCE - COMPLETE")
        logger.info(f" Processed: {total_patients} patients")
        logger.info(f" Found: {sum(1 for r in self.results if r.get('found'))}")
        logger.info("=" * 70)

        return {
            "patients": self.results,
            "hospital": self.hospital_type,
            "total": len(self.patient_names),
            "found_count": sum(1 for r in self.results if r.get("found")),
        }

    def _navigate_to_patient_list(self) -> bool:
        """
        Navigate to Jackson patient list.
        Reuses steps 1-8 from the standard Jackson flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH-INS] Navigating to patient list...")

        try:
            # Start OmniParser warmup in background
            start_warmup_async()

            # Reuse Jackson flow steps
            self._jackson_flow.step_1_tab()
            self._jackson_flow.step_2_powered()
            self._jackson_flow.step_3_open_download()
            self._jackson_flow.step_4_username()
            self._jackson_flow.step_5_password()
            self._jackson_flow.step_6_login_ok()

            # Handle info modal if appears
            self._handle_info_modal_after_login()

            self._jackson_flow.step_7_patient_list()
            self._jackson_flow.step_8_hospital_tab()

            stoppable_sleep(3)
            logger.info("[JACKSON-BATCH-INS] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[JACKSON-BATCH-INS] Navigation failed: {e}")
            return False

    def _handle_info_modal_after_login(self):
        """Handle info modal that may appear after login."""
        info_modal = self.wait_for_element(
            config.get_rpa_setting("images.jackson_info_modal"),
            timeout=3,
            description="Info Modal",
        )

        if info_modal:
            logger.info("[JACKSON-BATCH-INS] Info modal detected - dismissing")
            pydirectinput.press("enter")
            stoppable_sleep(2)

    def _find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the JacksonInsuranceRunner.

        Returns:
            True if patient found and clicked, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[JACKSON-BATCH-INS] Finding patient: {patient_name}")

        runner = JacksonInsuranceRunner(
            max_steps=15,
            step_delay=1.0,
        )

        result = runner.run(patient_name=patient_name)

        # Track if patient detail is open (for cleanup if error)
        self._patient_detail_open = getattr(result, "patient_detail_open", False)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[JACKSON-BATCH-INS] Patient not found: {patient_name}")
            return False

        # Check for other failures
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not complete"
            logger.error(
                f"[JACKSON-BATCH-INS] Agent error for {patient_name}: {error_msg}"
            )
            if self._patient_detail_open:
                logger.info("[JACKSON-BATCH-INS] Closing patient detail after error...")
                self._close_patient_detail()
            return False

        self._patient_detail_open = True
        logger.info(f"[JACKSON-BATCH-INS] Patient found in {result.steps_taken} steps")
        stoppable_sleep(2)
        return True

    def _extract_insurance(self) -> str:
        """
        Extract insurance content from Guarantors tab.

        Flow:
        1. Click 'More' button
        2. Click 'Insurance Information'
        3. Wait for and click 'Guarantors' tab
        4. Ctrl+A, Ctrl+C to copy content
        5. Alt+F4 to close insurance window
        """
        self.set_step("EXTRACT_INSURANCE")
        logger.info(
            f"[JACKSON-BATCH-INS] Extracting insurance for: {self.current_patient}"
        )

        # Step 1: Click More
        logger.info("[JACKSON-BATCH-INS] Step 1: Clicking 'More' button...")
        more_img = config.get_rpa_setting("images.jackson_more")
        location = self.wait_for_element(
            more_img,
            timeout=10,
            confidence=0.8,
            description="More button",
        )
        if not location:
            raise Exception("More button not found")
        self.safe_click(location, "More button")
        stoppable_sleep(2)

        # Step 2: Click Insurance Information
        logger.info("[JACKSON-BATCH-INS] Step 2: Clicking 'Insurance Information'...")
        insurance_info_img = config.get_rpa_setting(
            "images.jackson_insurance_information"
        )
        location = self.wait_for_element(
            insurance_info_img,
            timeout=10,
            confidence=0.8,
            description="Insurance Information",
        )
        if not location:
            raise Exception("Insurance Information not found")
        self.safe_click(location, "Insurance Information")
        stoppable_sleep(4)

        # Step 3: Wait for and Click Guarantors
        logger.info("[JACKSON-BATCH-INS] Step 3: Waiting for 'Guarantors' tab...")
        guarantors_img = config.get_rpa_setting("images.jackson_insurance_guarantors")
        location = self.wait_for_element(
            guarantors_img,
            timeout=15,
            confidence=0.8,
            description="Guarantors tab",
        )
        if not location:
            raise Exception("Guarantors tab not found")

        logger.info("[JACKSON-BATCH-INS] Step 4: Clicking 'Guarantors' tab...")
        self.safe_click(location, "Guarantors tab")
        stoppable_sleep(2)

        # Step 5: Select All and Copy
        logger.info("[JACKSON-BATCH-INS] Step 5: Selecting all and copying content...")
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
        content = pyperclip.paste()
        logger.info(f"[JACKSON-BATCH-INS] Copied {len(content)} characters")

        # Step 6: Close insurance window (Alt+F4)
        logger.info("[JACKSON-BATCH-INS] Step 6: Closing insurance window (Alt+F4)...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")
        stoppable_sleep(2)

        return content or ""

    def _close_patient_detail(self):
        """Close patient detail window (Alt+F4) without navigating to VDI."""
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # PowerChart can freeze during close - longer wait prevents Alt+F4 accumulation
        stoppable_sleep(15)
        self._patient_detail_open = False
        logger.info("[JACKSON-BATCH-INS] Patient detail closed")

    def _return_to_patient_list(self):
        """
        Close current patient detail and return to patient list.
        Uses Alt+F4 to close the patient detail view.
        Uses conservative wait (3x10s with center clicks) to confirm we're back.
        Does NOT retry Alt+F4 to avoid race conditions.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH-INS] Returning to patient list...")

        # Click center to ensure focus
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        logger.info("[JACKSON-BATCH-INS] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait 15 seconds for the system to process the close
        # PowerChart can freeze during close - longer wait prevents Alt+F4 accumulation
        logger.info("[JACKSON-BATCH-INS] Waiting 15s for system to process close...")
        stoppable_sleep(15)

        patient_list_header_img = config.get_rpa_setting(
            "images.jackson_patient_list_header"
        )

        # Use patient wait with multiple attempts (NO additional Alt+F4)
        header_found = self._wait_for_patient_list_with_patience(
            patient_list_header_img,
            max_attempts=3,
            attempt_timeout=15,
        )

        if header_found:
            logger.info("[JACKSON-BATCH-INS] OK - Patient list confirmed")
        else:
            # Log warning but do NOT send another Alt+F4
            logger.warning(
                "[JACKSON-BATCH-INS] Patient list header not detected after patience wait. "
                "Continuing anyway to avoid race condition."
            )

        self._patient_detail_open = False
        logger.info("[JACKSON-BATCH-INS] Back at patient list")

    def _cleanup(self):
        """Close Jackson EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[JACKSON-BATCH-INS] Cleanup - closing EMR...")

        screen_w, screen_h = pyautogui.size()

        # Close patient list with Alt+F4
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        stoppable_sleep(3)

        # Navigate to VDI desktop
        self._jackson_flow.step_11_vdi_tab()

        # Verify we're back at the lobby
        self.verify_lobby()

        logger.info("[JACKSON-BATCH-INS] Cleanup complete")

    def notify_completion(self, result):
        """Send consolidated insurance results to n8n webhook."""
        payload = {
            "status": "completed",
            "type": self.FLOW_TYPE,
            "execution_id": self.execution_id,
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
            "hospital": self.hospital_type,
            "patients": result.get("patients", []),
            "total": result.get("total", 0),
            "found_count": result.get("found_count", 0),
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        }

        response = self._send_to_batch_insurance_webhook_n8n(payload)
        logger.info(
            f"[N8N] Batch insurance notification sent - Status: {response.status_code}"
        )
        return response
