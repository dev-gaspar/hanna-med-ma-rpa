"""
Baptist Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Local agentic runner to find the patient and navigate to report
3. Traditional RPA to print report as PDF and extract text content
"""

import os
from datetime import datetime
from typing import Optional

import pyautogui
import pydirectinput

from config import config
from core.s3_client import get_s3_client
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_flow import BaseFlow
from .baptist import BaptistFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async

# Local runner with prompt chaining (replaces n8n AgentRunner)
from agentic.runners import BaptistSummaryRunner


class BaptistSummaryFlow(BaseFlow):
    """
    Hybrid RPA flow for retrieving patient summary from Baptist Health.

    Workflow:
    1. Warmup: Pre-heat OmniParser API in background
    2. Phase 1 (RPA): Navigate to patient list using existing Baptist flow steps 1-10
    3. Phase 2 (Agentic): Use local runner to find patient and navigate to report
    4. Phase 3 (RPA): Print report to PDF and extract text content
    5. Phase 4 (RPA): Cleanup - close horizon session and return to start
    """

    FLOW_NAME = "Baptist Patient Summary"
    FLOW_TYPE = "baptist_patient_summary"

    # PDF output path on desktop
    PDF_FILENAME = "baptis report.pdf"

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()
        self.patient_name: Optional[str] = None
        self.copied_content: Optional[str] = None

        # Reference to Baptist flow for reusing navigation steps
        self._baptist_flow = BaptistFlow()

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

        # Also setup the internal Baptist flow reference
        self._baptist_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[BAPTIST SUMMARY] Patient to find: {patient_name}")

    def execute(self):
        """Execute the hybrid flow for patient summary retrieval."""
        if not self.patient_name:
            raise ValueError("Patient name is required for summary flow")

        # Start OmniParser warmup in background BEFORE Phase 1
        start_warmup_async()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[BAPTIST SUMMARY] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[BAPTIST SUMMARY] Phase 1: Complete - Patient list visible")

        # Click fullscreen for better visualization during agentic phase
        logger.info("[BAPTIST SUMMARY] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Agentic - Find the patient and navigate to report
        logger.info(
            f"[BAPTIST SUMMARY] Phase 2: Starting agentic search for '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open = (
            self._phase2_agentic_find_report()
        )

        # Handle patient not found (detail NOT open - only patient list)
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[BAPTIST SUMMARY] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
            self._click_normalscreen()
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
                f"[BAPTIST SUMMARY] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )

            # Notify error to centralized n8n webhook
            self.notify_error(error_msg)

            self._click_normalscreen()

            # Choose cleanup based on whether patient detail is open
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

        logger.info("[BAPTIST SUMMARY] Phase 2: Complete - Report found")

        # Exit fullscreen before extracting content
        logger.info("[BAPTIST SUMMARY] Exiting fullscreen mode...")
        self._click_normalscreen()

        # Wait for screen to settle
        stoppable_sleep(2)

        # Phase 3: Print report to PDF and extract content
        logger.info("[BAPTIST SUMMARY] Phase 3: Extracting report content via PDF...")
        self._phase3_extract_content_via_pdf()
        logger.info("[BAPTIST SUMMARY] Phase 3: Complete - Content extracted")

        # Phase 4: Cleanup
        logger.info("[BAPTIST SUMMARY] Phase 4: Cleanup...")
        self._phase4_cleanup()
        logger.info("[BAPTIST SUMMARY] Phase 4: Complete")

        logger.info("[BAPTIST SUMMARY] Flow complete")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content or "[ERROR] No content extracted",
            "patient_found": True,
        }

    def _click_fullscreen(self):
        """Click fullscreen button for better visualization during agentic phase."""
        fullscreen_img = config.get_rpa_setting("images.baptist_fullscreen_btn")
        try:
            location = pyautogui.locateOnScreen(fullscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[BAPTIST SUMMARY] Clicked fullscreen button")
                stoppable_sleep(1)
            else:
                logger.warning(
                    "[BAPTIST SUMMARY] Fullscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[BAPTIST SUMMARY] Error clicking fullscreen: {e}")

    def _click_normalscreen(self):
        """Click normalscreen button to restore view after agentic phase."""
        normalscreen_img = config.get_rpa_setting("images.baptist_normalscreen_btn")
        try:
            location = pyautogui.locateOnScreen(normalscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[BAPTIST SUMMARY] Clicked normalscreen button")
                stoppable_sleep(1)
            else:
                logger.warning(
                    "[BAPTIST SUMMARY] Normalscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[BAPTIST SUMMARY] Error clicking normalscreen: {e}")

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Reuses steps 1-10 from the standard Baptist flow, then clicks patient list.
        """
        # Reuse Baptist step methods directly
        self._baptist_flow.step_1_open_vdi_desktop()
        self._baptist_flow.step_2_open_edge()
        self._baptist_flow.step_3_wait_pineapple_connect()
        self._baptist_flow.step_4_open_menu()
        self._baptist_flow.step_5_scroll_modal()
        self._baptist_flow.step_6_click_cerner()
        self._baptist_flow.step_7_wait_cerner_login()
        self._baptist_flow.step_8_click_favorites()
        self._baptist_flow.step_9_click_powerchart()
        self._baptist_flow.step_10_wait_powerchart_open()

        # Click on patient list button to open the first hospital's list
        logger.info("[BAPTIST SUMMARY] Clicking patient list button...")
        patient_list_btn = self._baptist_flow.wait_for_element(
            config.get_rpa_setting("images.patient_list"),
            timeout=10,
            description="Patient List button",
            auto_click=True,
        )
        if not patient_list_btn:
            raise Exception("Patient List not found")
        stoppable_sleep(3)

        logger.info("[BAPTIST SUMMARY] Patient list visible - ready for agentic phase")

    def _phase2_agentic_find_report(self) -> tuple:
        """
        Phase 2: Use local agentic runner to find patient and navigate to report.
        Uses prompt chaining with specialized agents (PatientFinder, ReportFinder).

        Returns:
            Tuple of (status, error_message, patient_detail_open):
            - ("success", None, True) if patient found and report opened
            - ("patient_not_found", error_msg, False) if patient not in list
            - ("error", error_msg, bool) if agent failed or ran out of steps
        """
        self.set_step("PHASE2_AGENTIC_FIND_REPORT")

        # Local runner with prompt chaining (PatientFinder + ReportFinder)
        runner = BaptistSummaryRunner(
            max_steps=30,
            step_delay=1.5,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(
                f"[BAPTIST SUMMARY] Agent signaled patient not found: {result.error}"
            )
            return ("patient_not_found", result.error, result.patient_detail_open)

        # Check for other failures (error, stopped, max steps reached)
        if result.status != AgentStatus.FINISHED:
            error_msg = (
                result.error
                or "Agent did not find the report (max steps reached or error)"
            )
            logger.error(f"[BAPTIST SUMMARY] Agent failed: {error_msg}")
            return ("error", error_msg, result.patient_detail_open)

        logger.info(f"[BAPTIST SUMMARY] Agent completed in {result.steps_taken} steps")

        # Give time for the report content to fully render
        stoppable_sleep(2)
        return ("success", None, True)

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup Baptist EMR session and return to lobby when patient not found.
        Only patient list is open (no patient detail).
        """
        logger.info("[BAPTIST SUMMARY] Performing cleanup (patient list only)...")
        try:
            self._phase4_cleanup()
        except Exception as e:
            logger.warning(f"[BAPTIST SUMMARY] Cleanup error (continuing): {e}")

        # Verify we're back at the lobby
        self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup when patient detail window is open (after Phase 2 partial completion).
        Need to close both patient detail and patient list.
        """
        logger.info("[BAPTIST SUMMARY] Performing cleanup (patient detail open)...")
        try:
            # First close patient detail with Alt+F4
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            logger.info("[BAPTIST SUMMARY] Sending Alt+F4 to close patient detail...")
            pyautogui.hotkey("alt", "F4")
            stoppable_sleep(2)

            # Then do normal cleanup for patient list
            self._phase4_cleanup()
        except Exception as e:
            logger.warning(f"[BAPTIST SUMMARY] Cleanup error (continuing): {e}")

        self.verify_lobby()

    def _phase3_extract_content_via_pdf(self):
        """
        Phase 3: Extract report content by printing to PDF and reading the text.

        Flow:
        1. Click on report document to focus
        2. Click print button in PowerChart
        3. Enter x2 (confirm print dialog)
        4. Wait 3 seconds
        5. Type "baptis report" as filename
        6. Enter to save
        7. Left arrow + Enter to confirm overwrite if exists
        8. Extract text from PDF
        """
        self.set_step("PHASE3_EXTRACT_PDF")

        # Step 1: Click on report document to focus
        logger.info("[BAPTIST SUMMARY] Step 1: Clicking report document...")
        report_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_report_document"),
            timeout=10,
            description="Report Document",
        )
        if report_element:
            self.safe_click(report_element, "Report Document")
        else:
            logger.warning(
                "[BAPTIST SUMMARY] Report document image not found, clicking center"
            )
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(1)

        # Step 2: Click print button
        logger.info("[BAPTIST SUMMARY] Step 2: Clicking print button...")
        print_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_print_powerchart"),
            timeout=10,
            description="Print PowerChart",
        )
        if print_element:
            self.safe_click(print_element, "Print PowerChart")
        else:
            raise Exception("Print button not found in PowerChart")
        stoppable_sleep(2)

        # Step 3: Enter x2 to confirm print dialogs
        logger.info("[BAPTIST SUMMARY] Step 3: Confirming print dialogs (Enter x2)...")
        pydirectinput.press("enter")
        stoppable_sleep(0.5)
        pydirectinput.press("enter")
        stoppable_sleep(4)  # Wait for save dialog to appear

        # Step 4: Ctrl+Alt to exit VDI focus (save dialog is on local machine)
        logger.info("[BAPTIST SUMMARY] Step 4: Exiting VDI focus with Ctrl+Alt...")
        pydirectinput.keyDown("ctrl")
        pydirectinput.keyDown("alt")
        pydirectinput.keyUp("alt")
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(1)

        # Step 5: Click on existing PDF file to select it for replacement
        logger.info("[BAPTIST SUMMARY] Step 5: Clicking on existing PDF file...")
        pdf_file_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_report_pdf"),
            timeout=10,
            description="Baptist Report PDF file",
        )
        if pdf_file_element:
            self.safe_click(pdf_file_element, "Baptist Report PDF file")
        else:
            logger.warning(
                "[BAPTIST SUMMARY] PDF file image not found, continuing anyway..."
            )
        stoppable_sleep(1)

        # Step 6: Press Enter to confirm file selection
        logger.info(
            "[BAPTIST SUMMARY] Step 6: Pressing Enter to confirm file selection..."
        )
        pydirectinput.press("enter")
        stoppable_sleep(1)

        # Step 7: Left arrow to select 'Replace' option
        logger.info(
            "[BAPTIST SUMMARY] Step 7: Pressing Left arrow to select Replace..."
        )
        pydirectinput.press("left")
        stoppable_sleep(0.3)

        # Step 8: Enter to confirm replacement
        logger.info(
            "[BAPTIST SUMMARY] Step 8: Pressing Enter to confirm replacement..."
        )
        pydirectinput.press("enter")
        stoppable_sleep(3)  # Wait for PDF to be saved

        # Step 8: Extract text from PDF
        logger.info("[BAPTIST SUMMARY] Step 8: Extracting text from PDF...")
        self._extract_pdf_content()

    def _extract_pdf_content(self):
        """Extract text content from the saved PDF file."""
        try:
            import PyPDF2

            # Build PDF path (on desktop)
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            pdf_path = os.path.join(desktop_path, self.PDF_FILENAME)

            if not os.path.exists(pdf_path):
                logger.error(f"[BAPTIST SUMMARY] PDF not found at: {pdf_path}")
                self.copied_content = "[ERROR] PDF file not found on desktop"
                return

            # Read PDF and extract text
            with open(pdf_path, "rb") as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                text_content = []

                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(page_text)

                self.copied_content = "\n".join(text_content)

            logger.info(
                f"[BAPTIST SUMMARY] Extracted {len(self.copied_content)} characters from PDF"
            )

        except ImportError:
            logger.error(
                "[BAPTIST SUMMARY] PyPDF2 not installed - cannot extract PDF content"
            )
            self.copied_content = "[ERROR] PyPDF2 library not available"
        except Exception as e:
            logger.error(f"[BAPTIST SUMMARY] Error extracting PDF content: {e}")
            self.copied_content = f"[ERROR] Failed to extract PDF: {e}"

    def _phase4_cleanup(self):
        """
        Phase 4: Close horizon session and return to start.

        Flow:
        1. Close horizon session (3 dots menu -> close session)
        2. Accept alert
        3. Return to start screen
        """
        self.set_step("PHASE4_CLEANUP")

        # Use Baptist cleanup steps (skip step_12_close_powerchart as we're already closed from PDF print)
        self._baptist_flow.step_13_close_horizon()
        self._baptist_flow.step_14_accept_alert()
        self._baptist_flow.step_15_return_to_start()

        logger.info("[BAPTIST SUMMARY] Cleanup complete")

    def notify_completion(self, result):
        """Notify n8n of completion with the content or patient-not-found status."""
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
