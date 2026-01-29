"""
Jackson Batch Summary Flow - Batch patient summary for Jackson Health.

Extends BaseBatchSummaryFlow to provide Jackson-specific implementation.
Keeps EMR session open while processing multiple patients in fullscreen mode.
"""

from typing import Optional

import pyautogui
import pyperclip
import pydirectinput

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_batch_summary import BaseBatchSummaryFlow
from .jackson import JacksonFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import JacksonSummaryRunner


class JacksonBatchSummaryFlow(BaseBatchSummaryFlow):
    """
    Batch summary flow for Jackson Health.

    Keeps the Jackson EMR session open in FULLSCREEN mode while processing
    multiple patients, returning consolidated results at the end.

    Flow:
    1. Navigate to patient list
    2. Enter fullscreen mode (better for agentic vision)
    3. For each patient:
       - Find patient and open report (agentic)
       - Extract content (Ctrl+A, Ctrl+C)
       - Close patient detail (Alt+F4) - return to list
       - Wait for list to stabilize
    4. Exit fullscreen mode
    5. Cleanup (close EMR, return to VDI)
    """

    FLOW_NAME = "Jackson Batch Summary"
    FLOW_TYPE = "jackson_batch_summary"
    EMR_TYPE = "jackson"  # Required for BaseFlow fullscreen methods

    def __init__(self):
        super().__init__()
        self._jackson_flow = JacksonFlow()
        self._patient_detail_open = False  # Track if patient detail window is open

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
        doctor_specialty=None,
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
        self.doctor_specialty = doctor_specialty
        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )
        if doctor_specialty:
            logger.info(f"[JACKSON-BATCH] Doctor specialty: {doctor_specialty}")

    def execute(self):
        """
        Override base execute to add fullscreen handling and proper timing.

        1. Navigate to patient list (once)
        2. Enter fullscreen mode
        3. For each patient: find, extract, return to list
        4. Exit fullscreen mode (only at the end)
        5. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" JACKSON BATCH SUMMARY - STARTING")
        logger.info("=" * 70)
        logger.info(f"[JACKSON-BATCH] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self.navigate_to_patient_list():
            logger.error("[JACKSON-BATCH] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Enter fullscreen mode for better agentic vision
        logger.info("[JACKSON-BATCH] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Process each patient in fullscreen mode
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            is_last_patient = idx == total_patients
            self.current_patient = patient
            self.current_content = None

            logger.info(
                f"[JACKSON-BATCH] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self.find_patient(patient)

                if found:
                    # Extract content while still in fullscreen
                    self.current_content = self.extract_content()
                    logger.info(f"[JACKSON-BATCH] Extracted content for {patient}")

                    # Close patient detail and return to list
                    # (unless this is the last patient - we'll handle that in cleanup)
                    if not is_last_patient:
                        self.return_to_patient_list()
                    else:
                        # For last patient, just mark that detail is open
                        self._patient_detail_open = True
                        logger.info(
                            "[JACKSON-BATCH] Last patient - keeping detail open for cleanup"
                        )
                else:
                    logger.warning(f"[JACKSON-BATCH] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(f"[JACKSON-BATCH] Error processing {patient}: {str(e)}")
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
        logger.info("[JACKSON-BATCH] Exiting fullscreen mode...")
        self._click_normalscreen()
        stoppable_sleep(3)  # Wait for screen to settle

        # Phase 3: Cleanup
        logger.info("[JACKSON-BATCH] Cleanup phase")
        self.cleanup()

        logger.info("=" * 70)
        logger.info(" JACKSON BATCH SUMMARY - COMPLETE")
        logger.info(f" Processed: {total_patients} patients")
        logger.info(f" Found: {sum(1 for r in self.results if r.get('found'))}")
        logger.info("=" * 70)

        return {
            "patients": self.results,
            "hospital": self.hospital_type,
            "total": len(self.patient_names),
            "found_count": sum(1 for r in self.results if r.get("found")),
        }

    def navigate_to_patient_list(self) -> bool:
        """
        Navigate to Jackson patient list.
        Reuses steps 1-8 from the standard Jackson flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH] Navigating to patient list...")

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

            # Handle info modal
            self._handle_info_modal_after_login()

            self._jackson_flow.step_7_patient_list()
            self._jackson_flow.step_8_hospital_tab()

            stoppable_sleep(3)
            logger.info("[JACKSON-BATCH] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[JACKSON-BATCH] Navigation failed: {e}")
            return False

    # _click_fullscreen and _click_normalscreen inherited from BaseFlow (uses EMR_TYPE)

    def find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the local agentic runner.
        Uses JacksonSummaryRunner with prompt chaining (PatientFinder + ReportFinder).

        Returns:
            True if patient found and report opened, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[JACKSON-BATCH] Finding patient: {patient_name}")

        # Use local runner with prompt chaining
        runner = JacksonSummaryRunner(
            max_steps=30,
            step_delay=1.0,
            doctor_specialty=self.doctor_specialty,
        )

        result = runner.run(patient_name=patient_name)

        # Store whether patient detail is open (for cleanup if error)
        self._patient_detail_open = result.patient_detail_open

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[JACKSON-BATCH] Patient not found: {patient_name}")
            return False

        # Check for other failures (error, stopped, max steps reached)
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not find the report"
            logger.error(f"[JACKSON-BATCH] Agent error for {patient_name}: {error_msg}")
            # If patient detail is open, we need to close it before continuing
            if self._patient_detail_open:
                logger.info("[JACKSON-BATCH] Closing patient detail after error...")
                self._close_patient_detail()
            return False

        logger.info(f"[JACKSON-BATCH] Patient found in {result.steps_taken} steps")
        stoppable_sleep(2)
        return True

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

        # Wait for patient detail to fully close
        stoppable_sleep(5)
        self._patient_detail_open = False
        logger.info("[JACKSON-BATCH] Patient detail closed")

    def extract_content(self) -> str:
        """
        Extract content from the current patient's Final Report.
        Uses Ctrl+A, Ctrl+C to copy content.
        """
        self.set_step("EXTRACT_CONTENT")
        logger.info(f"[JACKSON-BATCH] Extracting content for: {self.current_patient}")

        # Wait for report to fully render
        stoppable_sleep(2)

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
        Uses conservative wait (3x10s with center clicks) to confirm we're back.
        Does NOT retry Alt+F4 to avoid race conditions.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[JACKSON-BATCH] Returning to patient list...")

        # Click center to ensure focus
        logger.info("[JACKSON-BATCH] Clicking center to ensure focus...")
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        logger.info("[JACKSON-BATCH] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait 5 seconds for the system to process the close
        logger.info("[JACKSON-BATCH] Waiting 5s for system to process close...")
        stoppable_sleep(5)

        patient_list_header_img = config.get_rpa_setting(
            "images.jackson_patient_list_header"
        )

        # Use patient wait with multiple attempts (NO additional Alt+F4)
        header_found = self._wait_for_patient_list_with_patience(
            patient_list_header_img,
            max_attempts=3,
            attempt_timeout=10,
        )

        if header_found:
            logger.info("[JACKSON-BATCH] OK - Patient list confirmed")
        else:
            # Log warning but do NOT send another Alt+F4
            logger.warning(
                "[JACKSON-BATCH] Patient list header not detected after patience wait. "
                "Continuing anyway to avoid race condition."
            )

        self._patient_detail_open = False
        logger.info("[JACKSON-BATCH] Back at patient list")

    def cleanup(self):
        """
        Close Jackson EMR session completely.
        Handles both scenarios:
        - Patient detail is open (need 2 Alt+F4)
        - Only patient list is open (need 1 Alt+F4)
        """
        self.set_step("CLEANUP")
        logger.info("[JACKSON-BATCH] Cleanup - closing EMR...")

        screen_w, screen_h = pyautogui.size()

        # If patient detail is still open (last patient), close it first
        if self._patient_detail_open:
            logger.info("[JACKSON-BATCH] Closing last patient detail...")
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            stoppable_sleep(5)
            self._patient_detail_open = False

        # Now close the patient list/Jackson main window
        logger.info("[JACKSON-BATCH] Closing Jackson main window...")
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

        logger.info("[JACKSON-BATCH] Cleanup complete")

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
