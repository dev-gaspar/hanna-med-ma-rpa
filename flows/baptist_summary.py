"""
Baptist Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Agentic brain (n8n) to find the specific patient across hospital tabs
3. Traditional RPA to print report as PDF and extract text content
"""

import os
import threading
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
from agentic import AgentRunner
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer


class BaptistSummaryFlow(BaseFlow):
    """
    Hybrid RPA flow for retrieving patient summary from Baptist Health.

    Workflow:
    1. Phase 1 (RPA): Navigate to patient list using existing Baptist flow steps 1-10
    2. Warmup: Pre-heat OmniParser API for faster agentic execution
    3. Phase 2 (Agentic): Use n8n brain to find patient across hospital tabs and open notes
    4. Phase 3 (RPA): Print report to PDF and extract text content
    5. Phase 4 (RPA): Cleanup - close horizon session and return to start
    """

    FLOW_NAME = "Baptist Patient Summary"
    FLOW_TYPE = "baptist_patient_summary"

    # PDF output path on desktop
    PDF_FILENAME = "baptis report.pdf"

    # Webhook URL for the Baptist Summary brain in n8n (for agentic phase)
    BAPTIST_SUMMARY_BRAIN_URL = config.get_rpa_setting(
        "agentic.baptist_summary_brain_url"
    )

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

        # Start warming up OmniParser in background WHILE Phase 1 runs
        warmup_thread = threading.Thread(target=self._warmup_omniparser, daemon=True)
        logger.info("[BAPTIST SUMMARY] Starting OmniParser warmup in background...")
        warmup_thread.start()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[BAPTIST SUMMARY] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[BAPTIST SUMMARY] Phase 1: Complete - Patient list visible")

        # Wait for warmup to complete if still running
        if warmup_thread.is_alive():
            logger.info(
                "[BAPTIST SUMMARY] Waiting for OmniParser warmup to complete..."
            )
            warmup_thread.join(timeout=60)  # Max 60 seconds
        logger.info("[BAPTIST SUMMARY] OmniParser ready")

        # Phase 2: Agentic - Find the patient across hospital tabs
        logger.info(
            f"[BAPTIST SUMMARY] Phase 2: Starting agentic search for '{self.patient_name}'..."
        )
        self._phase2_agentic_find_patient()
        logger.info("[BAPTIST SUMMARY] Phase 2: Complete - Patient notes found")

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
        }

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

    def _warmup_omniparser(self):
        """
        Pre-heat the OmniParser API to reduce latency during agentic phase.
        Captures current screen and sends to OmniParser.
        """
        try:
            logger.info("[BAPTIST SUMMARY] Warmup: Capturing screen for OmniParser...")
            screen_capturer = get_screen_capturer()
            omniparser = get_omniparser_client()

            # Capture and parse current screen
            data_url = screen_capturer.capture_data_url()
            result = omniparser.parse_image(data_url)

            logger.info(
                f"[BAPTIST SUMMARY] Warmup: OmniParser detected {len(result.elements)} elements"
            )
        except Exception as e:
            logger.warning(f"[BAPTIST SUMMARY] Warmup failed (non-critical): {e}")

    def _phase2_agentic_find_patient(self):
        """
        Phase 2: Use the agentic brain to find the patient across hospital tabs.
        The n8n brain controls the navigation until it signals 'finish'.
        """
        if not self.BAPTIST_SUMMARY_BRAIN_URL:
            raise ValueError(
                "Baptist Summary brain URL not configured. Set agentic.baptist_summary_brain_url in config."
            )

        # Build the goal for the agentic runner
        goal = f"""
Find the patient "{self.patient_name}" in the Baptist Health PowerChart patient list.

INSTRUCTIONS:
1. Look at the current patient list visible on screen
2. Search for a patient matching the name "{self.patient_name}"
3. If patient is NOT found in current hospital tab, navigate to other hospital tabs at the top
4. There are 4 hospital tabs - check each one until you find the patient
5. Once you find the patient, click on their row to select them
6. Open their clinical notes/documents
7. Signal 'finish' when the patient's notes are visible

HOSPITAL TABS: You can click on hospital tabs at the top of the patient list to switch between hospitals.
"""

        logger.info(f"[BAPTIST SUMMARY] Agentic goal: Find '{self.patient_name}'")
        logger.info(
            f"[BAPTIST SUMMARY] Brain URL: {self.BAPTIST_SUMMARY_BRAIN_URL[:50]}..."
        )

        # Run the agentic loop
        runner = AgentRunner(
            n8n_webhook_url=self.BAPTIST_SUMMARY_BRAIN_URL,
            max_steps=config.get_rpa_setting("agentic.max_steps", 50),
            step_delay=config.get_rpa_setting("agentic.step_delay_seconds", 2.0),
            upload_screenshots=True,
        )

        result = runner.run(goal)

        if result.status.value == "error":
            raise Exception(f"Agentic phase failed: {result.error}")

        logger.info(
            f"[BAPTIST SUMMARY] Agentic phase completed in {result.steps_taken} steps"
        )

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
        stoppable_sleep(4)  # Wait for save dialog

        # Step 5: Type filename
        logger.info("[BAPTIST SUMMARY] Step 5: Typing filename 'baptis report'...")
        pydirectinput.typewrite("baptis report", interval=0.05)
        stoppable_sleep(0.5)

        # Step 6: Enter to save
        logger.info("[BAPTIST SUMMARY] Step 6: Pressing Enter to save...")
        pydirectinput.press("enter")
        stoppable_sleep(1)

        # Step 7: Left arrow + Enter (in case file exists - confirm overwrite)
        logger.info("[BAPTIST SUMMARY] Step 7: Confirming overwrite if needed...")
        pydirectinput.press("left")
        stoppable_sleep(0.3)
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
        """Notify n8n of successful completion with the content."""
        payload = {
            "execution_id": self.execution_id,
            "status": "completed",
            "type": self.FLOW_TYPE,
            "patient_name": result.get("patient_name"),
            "content": result.get("content"),
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
