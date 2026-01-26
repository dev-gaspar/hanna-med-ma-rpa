"""
Steward Batch Summary Flow - Batch patient summary for Steward Health (Meditech).

Extends BaseBatchSummaryFlow to provide Steward-specific implementation.
Keeps EMR session open while processing multiple patients via content extraction.
Uses local StewardSummaryRunner with ROI masking.
"""

from typing import Optional, List, Dict, Any

import pyautogui
import pydirectinput
import pyperclip

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_batch_summary import BaseBatchSummaryFlow
from .steward import StewardFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import StewardSummaryRunner


class StewardBatchSummaryFlow(BaseBatchSummaryFlow):
    """
    Batch summary flow for Steward Health (Meditech).

    Keeps the Steward EMR session open while processing multiple patients,
    extracting content via print preview + copy, returning consolidated results.

    Flow:
    1. Navigate to patient list (once)
    2. For each patient:
       - Find patient and navigate to report (agentic runner)
       - Extract content (print preview, copy)
       - Close document and return to patient list
    3. Cleanup (close EMR, return to VDI)
    """

    FLOW_NAME = "Steward Batch Summary"
    FLOW_TYPE = "steward_batch_summary"

    def __init__(self):
        super().__init__()
        self._steward_flow = StewardFlow()
        self._patient_detail_open = False
        self._current_reason_for_exam: Optional[str] = None

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
        # Also setup the internal Steward flow reference
        self._steward_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )
        if doctor_specialty:
            logger.info(f"[STEWARD-BATCH] Doctor specialty: {doctor_specialty}")

    def execute(self):
        """
        Override base execute to add proper timing and state tracking.

        1. Navigate to patient list (once)
        2. For each patient: find, extract, return to list
        3. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" STEWARD BATCH SUMMARY - STARTING")
        logger.info("=" * 70)
        logger.info(f"[STEWARD-BATCH] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self.navigate_to_patient_list():
            logger.error("[STEWARD-BATCH] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Phase 2: Process each patient
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            is_last_patient = idx == total_patients
            self.current_patient = patient
            self.current_content = None
            self._current_reason_for_exam = None

            logger.info(
                f"[STEWARD-BATCH] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self.find_patient(patient)

                if found:
                    # Extract content
                    self.current_content = self.extract_content()
                    logger.info(f"[STEWARD-BATCH] Extracted content for {patient}")

                    # Return to patient list
                    self.return_to_patient_list()
                else:
                    logger.warning(f"[STEWARD-BATCH] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(f"[STEWARD-BATCH] Error processing {patient}: {str(e)}")
                self.results.append(
                    {
                        "patient": patient,
                        "found": False,
                        "content": None,
                        "error": str(e),
                    }
                )
                # Try to recover by returning to patient list
                if self._patient_detail_open:
                    try:
                        self.return_to_patient_list()
                    except Exception:
                        logger.warning(
                            "[STEWARD-BATCH] Recovery failed - continuing with cleanup"
                        )

        # Phase 3: Cleanup
        logger.info("[STEWARD-BATCH] Cleanup phase")
        self.cleanup()

        logger.info("=" * 70)
        logger.info(" STEWARD BATCH SUMMARY - COMPLETE")
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
        Navigate to Steward patient list (Rounds Patients).
        Reuses steps 1-6 from the standard Steward flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[STEWARD-BATCH] Navigating to patient list...")

        try:
            # Start OmniParser warmup in background
            start_warmup_async()

            # Reuse Steward flow steps to get to patient list
            self._steward_flow.step_1_tab()
            self._steward_flow.step_2_favorite()
            self._steward_flow.step_3_meditech()
            self._steward_flow.step_4_login()
            self._steward_flow.step_5_open_session()
            self._steward_flow.step_6_navigate_menu_5()

            # Wait for step6_load_menu (indicates patient list is visible)
            logger.info("[STEWARD-BATCH] Waiting for menu (patient list visible)...")

            menu = self._steward_flow.robust_wait_for_element(
                config.get_rpa_setting("images.steward_load_menu_6"),
                target_description="Menu (step 6) - Patient list visible",
                handlers=self._steward_flow._get_sign_list_handlers(),
                timeout=config.get_timeout("steward.menu"),
            )

            if not menu:
                raise Exception("Menu not found - patient list not visible")

            stoppable_sleep(2)
            logger.info("[STEWARD-BATCH] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[STEWARD-BATCH] Navigation failed: {e}")
            return False

    def find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the local StewardSummaryRunner.
        The runner handles patient finding, reason extraction, and report navigation.

        Returns:
            True if patient found and report opened, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[STEWARD-BATCH] Finding patient: {patient_name}")

        # Use local runner with specialty
        runner = StewardSummaryRunner(
            max_steps=50,
            step_delay=1.5,
            vdi_enhance=False,  # Steward doesn't need VDI enhancement
            doctor_specialty=self.doctor_specialty,
        )

        result = runner.run(patient_name=patient_name)

        # Store reason for exam if found
        self._current_reason_for_exam = result.reason_for_exam

        # Track if patient detail is open
        self._patient_detail_open = result.patient_detail_open

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[STEWARD-BATCH] Patient not found: {patient_name}")
            return False

        # Check for other failures
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not find the report"
            logger.error(f"[STEWARD-BATCH] Agent error for {patient_name}: {error_msg}")
            # If patient detail is open, we need to close it before continuing
            if self._patient_detail_open:
                logger.info("[STEWARD-BATCH] Closing patient detail after error...")
                self.return_to_patient_list()
            return False

        logger.info(f"[STEWARD-BATCH] Patient found in {result.steps_taken} steps")
        if self._current_reason_for_exam:
            logger.info(
                f"[STEWARD-BATCH] Reason: {self._current_reason_for_exam[:50]}..."
            )

        stoppable_sleep(2)
        return True

    def extract_content(self) -> str:
        """
        Extract content from the current patient's report.
        Uses print preview, copy content, then close modals.
        Prepends reason_for_exam if available.
        """
        self.set_step("EXTRACT_CONTENT")
        logger.info(f"[STEWARD-BATCH] Extracting content for: {self.current_patient}")

        # === Step 1: Click Print Report Button ===
        print_btn = config.get_rpa_setting("images.steward_print_report_btn")
        logger.info("[STEWARD-BATCH] Waiting for Print Report button...")
        location = self.wait_for_element(
            print_btn, timeout=10, confidence=0.8, description="Print Report button"
        )
        if not location:
            raise Exception("Print Report button not found")

        self.safe_click(location, "Print Report button")
        stoppable_sleep(2)

        # === Step 2: Click OK Preview Button ===
        ok_btn = config.get_rpa_setting("images.steward_ok_preview_btn")
        logger.info("[STEWARD-BATCH] Waiting for OK Preview button...")
        location = self.wait_for_element(
            ok_btn, timeout=15, confidence=0.8, description="OK Preview button"
        )
        if not location:
            raise Exception("OK Preview button not found")

        self.safe_click(location, "OK Preview button")
        stoppable_sleep(3)

        # === Step 3: Wait for Document Tab (indicates content loaded) ===
        tab_btn = config.get_rpa_setting("images.steward_tab_document_btn")
        logger.info("[STEWARD-BATCH] Waiting for document tab to appear...")
        location = self.wait_for_element(
            tab_btn, timeout=30, confidence=0.8, description="Document tab"
        )
        if not location:
            raise Exception("Document tab not found - content may not have loaded")

        logger.info(
            "[STEWARD-BATCH] Document tab visible - waiting for content to load..."
        )
        stoppable_sleep(3)

        # === Step 4: Click Center + Ctrl+A + Ctrl+C to Copy ===
        logger.info("[STEWARD-BATCH] Clicking center and copying content...")
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Clear clipboard first
        pyperclip.copy("")
        stoppable_sleep(0.3)

        # Select all with Ctrl+A
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

        # Get copied content
        content = pyperclip.paste()
        logger.info(f"[STEWARD-BATCH] Copied {len(content)} characters")

        # === Step 5: Right-click on Document Tab ===
        logger.info("[STEWARD-BATCH] Right-clicking on document tab...")
        location = self.wait_for_element(
            tab_btn, timeout=5, confidence=0.8, description="Document tab (right-click)"
        )
        if location:
            center = pyautogui.center(location)
            pyautogui.rightClick(center.x, center.y)
            stoppable_sleep(1)
        else:
            logger.warning("[STEWARD-BATCH] Could not find tab for right-click")
            pyautogui.rightClick(screen_w // 2, 50)
            stoppable_sleep(1)

        # === Step 6: Click Close Tab Document Button ===
        close_tab_btn = config.get_rpa_setting("images.steward_close_tab_document_btn")
        logger.info("[STEWARD-BATCH] Clicking close tab button...")
        location = self.wait_for_element(
            close_tab_btn, timeout=5, confidence=0.7, description="Close tab button"
        )
        if location:
            self.safe_click(location, "Close tab button")
            stoppable_sleep(2)
        else:
            logger.warning("[STEWARD-BATCH] Close tab button not found, trying Escape")
            pydirectinput.press("escape")
            stoppable_sleep(1)

        # === Step 7: Click Close Modal Document Detail ===
        close_modal_btn = config.get_rpa_setting(
            "images.steward_close_modal_document_detail"
        )
        logger.info("[STEWARD-BATCH] Clicking close modal button...")
        location = self.wait_for_element(
            close_modal_btn,
            timeout=10,
            confidence=0.8,
            description="Close modal button",
        )
        if location:
            self.safe_click(location, "Close modal button")
            stoppable_sleep(2)
        else:
            logger.warning("[STEWARD-BATCH] Close modal button not found")

        # Prepend reason_for_exam if available
        if self._current_reason_for_exam and content:
            content = (
                f"REASON FOR EXAM: {self._current_reason_for_exam}\n\n"
                f"{'-' * 50}\n\n"
                f"{content}"
            )

        logger.info("[STEWARD-BATCH] Content capture complete")
        return content or ""

    def return_to_patient_list(self):
        """
        Close current patient detail and return to patient list (Rounds Patients).
        After extracting content, we need to navigate back from Provider Notes to
        the patient list for the next patient.

        Strategy:
        1. Click steward_close_meditech
        2. Check if steward_rounds_patients_view is visible
        3. If not visible, click steward_close_meditech again
        4. Repeat until patient list is visible or max attempts reached
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[STEWARD-BATCH] Returning to patient list...")

        close_image = config.get_rpa_setting("images.steward_close_meditech")
        rounds_view_image = config.get_rpa_setting(
            "images.steward_rounds_patients_view"
        )

        max_clicks = 5
        clicks_done = 0
        screen_w, screen_h = pyautogui.size()

        while clicks_done < max_clicks:
            # First check if we're already at the patient list
            try:
                rounds_visible = pyautogui.locateOnScreen(
                    rounds_view_image, confidence=0.8
                )
                if rounds_visible:
                    logger.info(
                        "[STEWARD-BATCH] Rounds Patients view visible - back at patient list"
                    )
                    self._patient_detail_open = False
                    return
            except Exception:
                pass

            # Click close button
            try:
                close_location = pyautogui.locateOnScreen(close_image, confidence=0.8)
                if close_location:
                    pyautogui.click(pyautogui.center(close_location))
                    clicks_done += 1
                    # Move mouse away to avoid hover state
                    pyautogui.moveTo(screen_w // 2, screen_h // 2)
                    logger.info(
                        f"[STEWARD-BATCH] Clicked close meditech ({clicks_done}/{max_clicks})"
                    )
                    stoppable_sleep(2)
                else:
                    logger.warning("[STEWARD-BATCH] Close button not found")
                    break
            except Exception as e:
                logger.warning(f"[STEWARD-BATCH] Error clicking close: {e}")
                break

        # Final verification
        try:
            rounds_visible = pyautogui.locateOnScreen(rounds_view_image, confidence=0.8)
            if rounds_visible:
                logger.info("[STEWARD-BATCH] Confirmed - back at patient list")
            else:
                logger.warning(
                    "[STEWARD-BATCH] Could not confirm Rounds Patients view visible"
                )
        except Exception:
            logger.warning("[STEWARD-BATCH] Could not verify patient list visibility")

        self._patient_detail_open = False
        logger.info("[STEWARD-BATCH] Back at patient list")

    def cleanup(self):
        """
        Close Steward EMR session completely.
        Uses step_15 through step_19 from StewardFlow.
        """
        self.set_step("CLEANUP")
        logger.info("[STEWARD-BATCH] Cleanup - closing EMR...")

        try:
            # If patient detail is still open (last patient), close modals first
            if self._patient_detail_open:
                logger.info("[STEWARD-BATCH] Closing last patient detail...")
                self.return_to_patient_list()

            # Now do the full cleanup using Steward flow steps
            # step_15 handles multiple clicks automatically
            self._steward_flow.step_15_close_meditech()

            # Right click on logged out tab (with fallback)
            self._steward_flow.step_16_tab_logged_out()

            # Close tab final
            self._steward_flow.step_17_close_tab_final()

            # Reset URL to Horizon home
            self._steward_flow.step_18_url()

            # Return to VDI Desktop
            self._steward_flow.step_19_vdi_tab()

            # Verify we're back at the lobby
            self.verify_lobby()

            logger.info("[STEWARD-BATCH] Cleanup complete")

        except Exception as e:
            logger.warning(f"[STEWARD-BATCH] Cleanup error: {e}")
            # Try to at least get back to lobby
            try:
                self.verify_lobby()
            except Exception:
                pass
