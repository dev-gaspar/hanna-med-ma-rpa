"""
Steward Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

Phases:
- Phase 1 (RPA): Navigate to patient list using Steward flow steps
- Phase 2 (Agentic Runner): Find patient, extract reason, navigate to report
  - PatientFinderAgent - Find patient in Rounds Patients list
  - RPA - Click patient and open Orders view
  - ReasonFinderAgent - Extract "Reason For Exam" from Orders
  - RPA - Navigate to Chart > Provider Notes
  - ReportFinderAgent - Find clinical document in list
- Phase 3 (RPA): Capture document content (print preview, copy, close modals)
- Phase 4 (RPA): Cleanup and return to lobby

Note: This follows the same pattern as Jackson and Baptist flows.
The runner finds the report, the flow captures content and cleans up.
"""

from datetime import datetime
from typing import Optional

import pyautogui
import pydirectinput
import pyperclip

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_flow import BaseFlow
from .steward import StewardFlow

from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import StewardSummaryRunner


class StewardSummaryFlow(BaseFlow):
    """
    Hybrid RPA flow for retrieving patient summary from Steward Health (Meditech).

    Workflow:
    1. Phase 1 (RPA): Navigate to patient list
    2. Phase 2 (Agentic Runner): Find patient, extract reason, navigate to report
    3. Phase 3 (RPA): Capture document content
    4. Phase 4 (RPA): Cleanup and return to lobby
    """

    FLOW_NAME = "Steward Patient Summary"
    FLOW_TYPE = "steward_patient_summary"

    def __init__(self):
        super().__init__()
        self.patient_name: Optional[str] = None
        self.copied_content: Optional[str] = None
        self.reason_for_exam: Optional[str] = None
        self.doctor_specialty: Optional[str] = None

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

        # Also setup the internal Steward flow reference
        self._steward_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[STEWARD SUMMARY] Patient to find: {patient_name}")
        if doctor_specialty:
            logger.info(f"[STEWARD SUMMARY] Doctor specialty: {doctor_specialty}")

    def execute(self):
        """Execute the hybrid flow for patient summary retrieval."""
        if not self.patient_name:
            raise ValueError("Patient name is required for summary flow")

        logger.info("=" * 70)
        logger.info(" STEWARD SUMMARY FLOW - STARTING")
        logger.info("=" * 70)

        # Start OmniParser warmup in background BEFORE Phase 1
        start_warmup_async()

        # =====================================================================
        # PHASE 1: Traditional RPA - Navigate to patient list
        # STATUS: IMPLEMENTED - This works!
        # =====================================================================
        logger.info("[STEWARD SUMMARY] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[STEWARD SUMMARY] Phase 1: Complete - Patient list visible")

        # =====================================================================
        # PHASE 2: Agentic - Find patient, extract reason, navigate to report
        # The runner finds the report, we capture content here
        # =====================================================================
        logger.info(
            f"[STEWARD SUMMARY] Phase 2: Starting agentic search for '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open, reason_for_exam = (
            self._phase2_agentic_find_document()
        )

        # Store reason for exam if found
        if reason_for_exam:
            self.reason_for_exam = reason_for_exam

        # Handle patient not found
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[STEWARD SUMMARY] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
            self._cleanup_and_return_to_lobby()
            return {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "reason_for_exam": None,
                "error": f"Patient '{self.patient_name}' not found in patient list",
            }

        # Handle agent error
        if phase2_status == "error":
            error_msg = f"Agent failed: {phase2_error}"
            logger.error(
                f"[STEWARD SUMMARY] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )

            # Cleanup based on state
            if patient_detail_open:
                self._cleanup_with_patient_detail_open()
            else:
                self._cleanup_and_return_to_lobby()

            # Raise exception so BaseFlow.run() calls notify_error()
            raise Exception(error_msg)

        # =====================================================================
        # PHASE 3: RPA - Capture document content
        # Print preview, copy content, close modals
        # =====================================================================
        logger.info("[STEWARD SUMMARY] Phase 2 complete - Report found")
        logger.info("[STEWARD SUMMARY] Phase 3: Capturing document content...")

        self._phase3_capture_content()

        # Concatenate reason at the beginning of content
        if self.reason_for_exam and self.copied_content:
            self.copied_content = (
                f"REASON FOR EXAM: {self.reason_for_exam}\n\n"
                f"{'-' * 50}\n\n"
                f"{self.copied_content}"
            )

        logger.info(
            f"[STEWARD SUMMARY] Phase 3 complete - {len(self.copied_content or '')} chars"
        )

        # =====================================================================
        # PHASE 4: RPA - Cleanup and return to lobby
        # =====================================================================
        logger.info("[STEWARD SUMMARY] Phase 4: Cleanup and return to lobby...")
        self._phase4_cleanup()

        logger.info("[STEWARD SUMMARY] Complete - Content ready")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content,
            "patient_found": True,
            "reason_for_exam": self.reason_for_exam,
        }

    # =========================================================================
    # PHASE 1: RPA Navigation - IMPLEMENTED
    # =========================================================================

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Navigates until step6_load_menu (three lines menu) is visible.
        At this point, the patient list "Rounds Patients" is visible.

        STATUS: IMPLEMENTED - This works!
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
        # This indicates the patient list is visible
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

    # =========================================================================
    # PHASE 2: Agentic - Find patient, reason, and report
    # =========================================================================

    def _phase2_agentic_find_document(self) -> tuple:
        """
        Phase 2: Use local agentic runner to find patient, extract reason, and navigate to report.

        The runner handles phases 2-6 internally:
        - PatientFinderAgent - Find patient in list
        - RPA - Click patient and open Orders
        - ReasonFinderAgent - Extract Reason For Exam
        - RPA - Navigate to Provider Notes
        - ReportFinderAgent - Find clinical document

        Note: Content capture (Phase 3) is handled by the flow, not the runner.

        Returns:
            Tuple of (status, error_message, patient_detail_open, reason_for_exam)
        """
        self.set_step("PHASE2_AGENTIC_FIND_DOCUMENT")

        runner = StewardSummaryRunner(
            max_steps=50,
            step_delay=1.5,
            doctor_specialty=self.doctor_specialty,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            return ("patient_not_found", result.error, result.patient_detail_open, None)

        # Check for other failures
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent error"
            return (
                "error",
                error_msg,
                result.patient_detail_open,
                result.reason_for_exam,
            )

        # Success - report found
        return ("success", None, True, result.reason_for_exam)

    # =========================================================================
    # PHASE 3: Capture Content - RPA
    # =========================================================================

    def _phase3_capture_content(self):
        """
        Phase 3: Capture document content using RPA.

        Steps:
        1. Click Print Report button to generate preview
        2. Click OK on preview dialog
        3. Wait for document tab to appear (indicates content loaded)
        4. Click center + Ctrl+A + Ctrl+C to copy content
        5. Right-click on document tab
        6. Close document tab
        7. Close document detail modal
        """
        self.set_step("PHASE3_CAPTURE_CONTENT")

        # === Step 1: Click Print Report Button ===
        print_btn = config.get_rpa_setting("images.steward_print_report_btn")
        logger.info("[PHASE 3] Waiting for Print Report button...")
        location = self.wait_for_element(
            print_btn, timeout=10, confidence=0.8, description="Print Report button"
        )
        if not location:
            raise Exception("Print Report button not found")

        self.safe_click(location, "Print Report button")
        stoppable_sleep(2)

        # === Step 2: Click OK Preview Button ===
        ok_btn = config.get_rpa_setting("images.steward_ok_preview_btn")
        logger.info("[PHASE 3] Waiting for OK Preview button...")
        location = self.wait_for_element(
            ok_btn, timeout=15, confidence=0.8, description="OK Preview button"
        )
        if not location:
            raise Exception("OK Preview button not found")

        self.safe_click(location, "OK Preview button")
        stoppable_sleep(3)

        # === Step 3: Wait for Document Tab (indicates content loaded) ===
        tab_btn = config.get_rpa_setting("images.steward_tab_document_btn")
        logger.info("[PHASE 3] Waiting for document tab to appear...")
        location = self.wait_for_element(
            tab_btn, timeout=30, confidence=0.8, description="Document tab"
        )
        if not location:
            raise Exception("Document tab not found - content may not have loaded")

        logger.info(
            "[PHASE 3] Document tab visible - waiting for content to fully load..."
        )
        stoppable_sleep(3)

        # === Step 4: Click Center + Ctrl+A + Ctrl+C to Copy ===
        logger.info("[PHASE 3] Clicking center and copying content...")
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
        self.copied_content = pyperclip.paste()
        logger.info(f"[PHASE 3] Copied {len(self.copied_content)} characters")

        # === Step 5: Right-click on Document Tab ===
        logger.info("[PHASE 3] Right-clicking on document tab...")
        location = self.wait_for_element(
            tab_btn, timeout=5, confidence=0.8, description="Document tab (right-click)"
        )
        if location:
            center = pyautogui.center(location)
            pyautogui.rightClick(center.x, center.y)
            stoppable_sleep(1)
        else:
            logger.warning(
                "[PHASE 3] Could not find tab for right-click, trying center"
            )
            pyautogui.rightClick(screen_w // 2, 50)
            stoppable_sleep(1)

        # === Step 6: Click Close Tab Document Button ===
        close_tab_btn = config.get_rpa_setting("images.steward_close_tab_document_btn")
        logger.info("[PHASE 3] Clicking close tab button...")
        location = self.wait_for_element(
            close_tab_btn, timeout=5, confidence=0.7, description="Close tab button"
        )
        if location:
            self.safe_click(location, "Close tab button")
            stoppable_sleep(2)
        else:
            # Try pressing Escape as fallback
            logger.warning("[PHASE 3] Close tab button not found, trying Escape")
            pydirectinput.press("escape")
            stoppable_sleep(1)

        # === Step 7: Click Close Modal Document Detail ===
        close_modal_btn = config.get_rpa_setting(
            "images.steward_close_modal_document_detail"
        )
        logger.info("[PHASE 3] Clicking close modal button...")
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
            logger.warning("[PHASE 3] Close modal button not found")

        logger.info("[PHASE 3] Content capture complete")

    # =========================================================================
    # PHASE 4: Cleanup - Return to lobby
    # =========================================================================

    def _phase4_cleanup(self):
        """
        Phase 4: Cleanup Meditech session and return to lobby.

        Called after content has been captured in Phase 3.
        """
        self.set_step("PHASE4_CLEANUP")

        # Cleanup and return to lobby
        self._cleanup_with_patient_detail_open()

    # =========================================================================
    # CLEANUP METHODS - IMPLEMENTED
    # =========================================================================

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup Meditech session and return to lobby.
        Uses Steward flow steps 15-19 exactly as in steward.py:
        - step_15_close_meditech (2 clicks + verification loop)
        - step_16_tab_logged_out
        - step_17_close_tab_final
        - step_18_url
        - step_19_vdi_tab
        """
        logger.info("[STEWARD SUMMARY] Cleaning up and returning to lobby...")
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

            logger.info("[STEWARD SUMMARY] Cleanup completed successfully")

        except Exception as e:
            logger.warning(f"[STEWARD SUMMARY] Cleanup error (continuing): {e}")
            # Try to at least get back to lobby
            self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup when patient chart/Orders detail is open.
        step_15 now handles multiple clicks automatically via verification loop.
        Then continues with steps 16-19.
        """
        logger.info("[STEWARD SUMMARY] Cleaning up with patient detail open...")
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
                "[STEWARD SUMMARY] Cleanup (patient open) completed successfully"
            )

        except Exception as e:
            logger.warning(f"[STEWARD SUMMARY] Cleanup error (continuing): {e}")
            self.verify_lobby()

    def _handle_close_confirmations(self):
        """
        Handle confirmation dialogs when closing Meditech.
        Looks for Leave Now button and clicks it if present.
        """
        self._steward_flow._handle_warning_leave_now_modal()

    # =========================================================================
    # NOTIFICATION
    # =========================================================================

    def notify_completion(self, result):
        """Notify n8n of completion."""
        patient_found = result.get("patient_found", True)
        payload = {
            "execution_id": self.execution_id,
            "status": "completed" if patient_found else "patient_not_found",
            "type": self.FLOW_TYPE,
            "patient_name": result.get("patient_name"),
            "content": result.get("content"),
            "reason_for_exam": result.get("reason_for_exam"),
            "patient_found": patient_found,
            "error": result.get("error"),
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
            "doctor_specialty": self.doctor_specialty,
        }
        response = self._send_to_summary_webhook_n8n(payload)
        logger.info(f"[N8N] Summary notification sent - Status: {response.status_code}")
        return response
