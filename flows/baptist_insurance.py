"""
Baptist Insurance Flow - RPA + Agentic flow for patient insurance extraction.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Local agentic runner (PatientFinder) to find the patient
3. Traditional RPA to click Provider Face Sheet and extract insurance via PDF
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

# Dedicated runner for insurance flow (PatientFinder + Face Sheet)
from agentic.runners import BaptistInsuranceRunner


class BaptistInsuranceFlow(BaseFlow):
    """
    RPA flow for extracting patient insurance from Baptist Health.

    Workflow:
    1. Warmup: Pre-heat OmniParser API in background
    2. Phase 1 (RPA): Navigate to patient list using existing Baptist flow steps 1-10
    3. Phase 2 (Agentic): Use PatientFinder to locate patient
    4. Phase 3 (RPA): Click Provider Face Sheet button
    5. Phase 4 (RPA): Print insurance to PDF and extract content
    6. Phase 5 (RPA): Cleanup - close horizon session and return to start
    """

    FLOW_NAME = "Baptist Patient Insurance"
    FLOW_TYPE = "baptist_patient_insurance"
    EMR_TYPE = "baptist"

    # PDF output path on desktop
    PDF_FILENAME = "baptis insurance.pdf"

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

        logger.info(f"[BAPTIST INSURANCE] Patient to find: {patient_name}")

    def execute(self):
        """Execute the flow for patient insurance extraction."""
        if not self.patient_name:
            raise ValueError("Patient name is required for insurance flow")

        # Start OmniParser warmup in background BEFORE Phase 1
        start_warmup_async()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[BAPTIST INSURANCE] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[BAPTIST INSURANCE] Phase 1: Complete - Patient list visible")

        # Click fullscreen BEFORE agentic phase (required for PatientFinder)
        logger.info("[BAPTIST INSURANCE] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Agentic - Find patient + Click Face Sheet
        # BaptistInsuranceRunner handles both steps
        logger.info(
            f"[BAPTIST INSURANCE] Phase 2: Finding patient and opening Face Sheet '{self.patient_name}'..."
        )
        phase2_status, phase2_error, patient_detail_open = (
            self._phase2_agentic_find_and_open_face_sheet()
        )

        # Handle patient not found
        if phase2_status == "patient_not_found":
            logger.warning(
                f"[BAPTIST INSURANCE] Patient '{self.patient_name}' NOT FOUND - cleaning up..."
            )
            self._click_normalscreen()
            self._cleanup_and_return_to_lobby()
            return {
                "patient_name": self.patient_name,
                "content": None,
                "patient_found": False,
                "error": f"Patient '{self.patient_name}' not found in patient list",
            }

        # Handle agent error
        if phase2_status == "error":
            error_msg = f"Agent failed: {phase2_error}"
            logger.error(
                f"[BAPTIST INSURANCE] Agent FAILED for '{self.patient_name}' - cleaning up..."
            )
            self.notify_error(error_msg)
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

        logger.info("[BAPTIST INSURANCE] Phase 2: Complete - Face Sheet open")

        # Phase 3: Print insurance to PDF and extract content
        # Stay in fullscreen, no need to exit
        logger.info(
            "[BAPTIST INSURANCE] Phase 3: Extracting insurance content via PDF..."
        )
        self._phase3_extract_insurance_via_pdf()
        logger.info("[BAPTIST INSURANCE] Phase 3: Complete - Content extracted")

        # Phase 4: Cleanup
        logger.info("[BAPTIST INSURANCE] Phase 4: Cleanup...")
        self._phase4_cleanup()
        logger.info("[BAPTIST INSURANCE] Phase 4: Complete")

        logger.info("[BAPTIST INSURANCE] Flow complete")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content or "[ERROR] No content extracted",
            "patient_found": True,
        }

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Reuses steps 1-10 from the standard Baptist flow.
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

        # Click on patient list button
        logger.info("[BAPTIST INSURANCE] Clicking patient list button...")
        patient_list_btn = self._baptist_flow.wait_for_element(
            config.get_rpa_setting("images.patient_list"),
            timeout=10,
            description="Patient List button",
            auto_click=True,
        )
        if not patient_list_btn:
            raise Exception("Patient List not found")
        stoppable_sleep(3)

        logger.info(
            "[BAPTIST INSURANCE] Patient list visible - ready for agentic phase"
        )

    def _phase2_agentic_find_and_open_face_sheet(self) -> tuple:
        """
        Phase 2: Use BaptistInsuranceRunner to find patient and open Face Sheet.

        The runner:
        1. Uses PatientFinder to locate patient (returns element ID)
        2. Double-clicks patient to open detail
        3. Clicks Provider Face Sheet button

        Returns:
            Tuple of (status, error_message, patient_detail_open)
        """
        self.set_step("PHASE2_AGENTIC_FIND_AND_FACE_SHEET")

        runner = BaptistInsuranceRunner(
            max_steps=15,
            step_delay=1.5,
        )

        result = runner.run(patient_name=self.patient_name)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(
                f"[BAPTIST INSURANCE] Agent signaled patient not found: {result.error}"
            )
            return ("patient_not_found", result.error, result.patient_detail_open)

        # Check for failures
        if result.status != AgentStatus.FINISHED:
            error_msg = (
                result.error or "Agent did not complete (max steps reached or error)"
            )
            logger.error(f"[BAPTIST INSURANCE] Agent failed: {error_msg}")
            return ("error", error_msg, result.patient_detail_open)

        logger.info(
            f"[BAPTIST INSURANCE] Agent completed in {result.steps_taken} steps"
        )
        stoppable_sleep(2)
        return ("success", None, True)

    def _phase3_extract_insurance_via_pdf(self):
        """
        Phase 4: Extract insurance by printing to PDF.

        Flow:
        1. Click Print button
        2. Press Enter (confirm print)
        3. Click on Baptist Insurance image in print dialog
        4. Press Enter to save
        5. Press Left arrow + Enter to confirm overwrite
        6. Extract text from PDF
        """
        self.set_step("PHASE4_EXTRACT_INSURANCE_PDF")

        # Step 1: Click print button
        logger.info("[BAPTIST INSURANCE] Step 1: Clicking print button...")
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

        # Step 2: Press Enter to confirm print
        logger.info("[BAPTIST INSURANCE] Step 2: Pressing Enter to confirm print...")
        pydirectinput.press("enter")
        stoppable_sleep(3)

        # Step 3: Ctrl+Alt to exit VDI focus (save dialog is on local machine)
        logger.info("[BAPTIST INSURANCE] Step 3: Exiting VDI focus with Ctrl+Alt...")
        pydirectinput.keyDown("ctrl")
        pydirectinput.keyDown("alt")
        pydirectinput.keyUp("alt")
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(2)

        # Step 4: Click on Baptist Insurance document (existing file)
        logger.info(
            "[BAPTIST INSURANCE] Step 4: Clicking Baptist Insurance document..."
        )
        insurance_img = config.get_rpa_setting("images.baptist_insurance_btn")
        insurance_element = self.wait_for_element(
            insurance_img,
            timeout=10,
            description="Baptist Insurance document",
        )
        if insurance_element:
            self.safe_click(insurance_element, "Baptist Insurance document")
        else:
            logger.warning(
                "[BAPTIST INSURANCE] Baptist Insurance document not found, continuing..."
            )
        stoppable_sleep(2)

        # Step 5: Press Enter to confirm
        logger.info("[BAPTIST INSURANCE] Step 5: Pressing Enter to confirm...")
        pydirectinput.press("enter")
        stoppable_sleep(2)

        # Step 6: Left arrow to select 'Replace' option
        logger.info(
            "[BAPTIST INSURANCE] Step 6: Pressing Left arrow to select Replace..."
        )
        pydirectinput.press("left")
        stoppable_sleep(2)

        # Step 7: Enter to confirm replacement
        logger.info(
            "[BAPTIST INSURANCE] Step 7: Pressing Enter to confirm replacement..."
        )
        pydirectinput.press("enter")
        stoppable_sleep(3)  # Wait for PDF to be saved

        # Step 8: Extract text from PDF
        logger.info("[BAPTIST INSURANCE] Step 8: Extracting text from PDF...")
        self._extract_pdf_content()

    def _extract_pdf_content(self):
        """Extract text content from the saved PDF file."""
        try:
            import PyPDF2

            # Build PDF path (on desktop)
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            pdf_path = os.path.join(desktop_path, self.PDF_FILENAME)

            if not os.path.exists(pdf_path):
                logger.error(f"[BAPTIST INSURANCE] PDF not found at: {pdf_path}")
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
                f"[BAPTIST INSURANCE] Extracted {len(self.copied_content)} characters from PDF"
            )

        except ImportError:
            logger.error(
                "[BAPTIST INSURANCE] PyPDF2 not installed - cannot extract PDF content"
            )
            self.copied_content = "[ERROR] PyPDF2 library not available"
        except Exception as e:
            logger.error(f"[BAPTIST INSURANCE] Error extracting PDF content: {e}")
            self.copied_content = f"[ERROR] Failed to extract PDF: {e}"

    def _phase4_cleanup(self):
        """
        Phase 4: Close horizon session and return to start.
        """
        self.set_step("PHASE4_CLEANUP")

        # Use Baptist cleanup steps
        self._baptist_flow.step_13_close_horizon()
        self._baptist_flow.step_14_accept_alert()
        self._baptist_flow.step_15_return_to_start()

        logger.info("[BAPTIST INSURANCE] Cleanup complete")

    def _cleanup_and_return_to_lobby(self):
        """
        Cleanup when patient not found (only patient list open).
        """
        logger.info("[BAPTIST INSURANCE] Performing cleanup (patient list only)...")
        try:
            self._phase4_cleanup()
        except Exception as e:
            logger.warning(f"[BAPTIST INSURANCE] Cleanup error (continuing): {e}")

        self.verify_lobby()

    def _cleanup_with_patient_detail_open(self):
        """
        Cleanup when patient detail window is open.
        """
        logger.info("[BAPTIST INSURANCE] Performing cleanup (patient detail open)...")
        try:
            # First close patient detail with Alt+F4
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            logger.info("[BAPTIST INSURANCE] Sending Alt+F4 to close patient detail...")
            pyautogui.hotkey("alt", "F4")
            stoppable_sleep(2)

            # Then do normal cleanup
            self._phase4_cleanup()
        except Exception as e:
            logger.warning(f"[BAPTIST INSURANCE] Cleanup error (continuing): {e}")

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
