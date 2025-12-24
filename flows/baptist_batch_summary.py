"""
Baptist Batch Summary Flow - Batch patient summary for Baptist Health.

Extends BaseBatchSummaryFlow to provide Baptist-specific implementation.
Keeps EMR session open while processing multiple patients via PDF extraction.
"""

import os
import threading
from typing import Optional

import pyautogui
import pydirectinput

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_batch_summary import BaseBatchSummaryFlow
from .baptist import BaptistFlow
from agentic import AgentRunner
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer


class BaptistBatchSummaryFlow(BaseBatchSummaryFlow):
    """
    Batch summary flow for Baptist Health.

    Keeps the Baptist EMR session open while processing multiple patients,
    extracting content via PDF printing, returning consolidated results.
    """

    FLOW_NAME = "Baptist Batch Summary"
    FLOW_TYPE = "baptist_batch_summary"

    PDF_FILENAME = "baptis report.pdf"

    # Webhook URL for the Baptist Summary brain
    BAPTIST_SUMMARY_BRAIN_URL = config.get_rpa_setting(
        "agentic.baptist_summary_brain_url"
    )

    def __init__(self):
        super().__init__()
        self._baptist_flow = BaptistFlow()
        self._omniparser_warmed = False

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
            patient_names=patient_names,
            hospital_type=hospital_type,
            **kwargs,
        )
        # Also setup the internal Baptist flow reference
        self._baptist_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )

    def navigate_to_patient_list(self) -> bool:
        """
        Navigate to Baptist patient list.
        Reuses steps 1-10 from the standard Baptist flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH] Navigating to patient list...")

        try:
            # Warmup OmniParser in background
            warmup_thread = threading.Thread(
                target=self._warmup_omniparser, daemon=True
            )
            warmup_thread.start()

            # Reuse Baptist flow steps
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

            # Click patient list
            logger.info("[BAPTIST-BATCH] Clicking patient list...")
            patient_list_btn = self._baptist_flow.wait_for_element(
                config.get_rpa_setting("images.patient_list"),
                timeout=10,
                description="Patient List button",
                auto_click=True,
            )
            if not patient_list_btn:
                raise Exception("Patient List not found")
            stoppable_sleep(3)

            # Wait for warmup
            if warmup_thread.is_alive():
                warmup_thread.join(timeout=60)

            logger.info("[BAPTIST-BATCH] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[BAPTIST-BATCH] Navigation failed: {e}")
            return False

    def find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the agentic brain.

        Returns:
            True if patient found, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[BAPTIST-BATCH] Finding patient: {patient_name}")

        if not self.BAPTIST_SUMMARY_BRAIN_URL:
            raise ValueError("Baptist Summary brain URL not configured")

        goal = f"""
Find the patient "{patient_name}" in the Baptist Health PowerChart patient list.

INSTRUCTIONS:
1. Look at the current patient list visible on screen
2. Search for a patient matching the name "{patient_name}"
3. If patient is NOT found in current hospital tab, navigate to other hospital tabs at the top
4. There are 4 hospital tabs - check each one until you find the patient
5. Once you find the patient, click on their row to select them
6. Open their clinical notes/documents
7. Signal 'finish' when the patient's notes are visible
8. If you have checked ALL 4 hospital tabs and cannot find the patient, signal 'patient_not_found'
"""

        runner = AgentRunner(
            n8n_webhook_url=self.BAPTIST_SUMMARY_BRAIN_URL,
            max_steps=config.get_rpa_setting("agentic.max_steps", 50),
            step_delay=config.get_rpa_setting("agentic.step_delay_seconds", 2.0),
            upload_screenshots=True,
        )

        result = runner.run(goal)

        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[BAPTIST-BATCH] Patient not found: {patient_name}")
            return False

        if result.status == AgentStatus.ERROR:
            logger.error(f"[BAPTIST-BATCH] Agent error: {result.error}")
            return False

        logger.info(f"[BAPTIST-BATCH] Patient found in {result.steps_taken} steps")
        return True

    def extract_content(self) -> str:
        """
        Extract content via PDF printing and text extraction.
        """
        self.set_step("EXTRACT_CONTENT")
        logger.info(f"[BAPTIST-BATCH] Extracting content for: {self.current_patient}")

        # Click report document to focus
        report_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_report_document"),
            timeout=10,
            description="Report Document",
        )
        if report_element:
            self.safe_click(report_element, "Report Document")
        else:
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(1)

        # Click print button
        print_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_print_powerchart"),
            timeout=10,
            description="Print PowerChart",
        )
        if print_element:
            self.safe_click(print_element, "Print PowerChart")
        else:
            raise Exception("Print button not found")
        stoppable_sleep(2)

        # Confirm print dialogs
        pydirectinput.press("enter")
        stoppable_sleep(0.5)
        pydirectinput.press("enter")
        stoppable_sleep(4)

        # Exit VDI focus (Ctrl+Alt)
        pydirectinput.keyDown("ctrl")
        pydirectinput.keyDown("alt")
        pydirectinput.keyUp("alt")
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(1)

        # Click existing PDF file to select
        pdf_file_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_report_pdf"),
            timeout=10,
            description="Baptist Report PDF file",
        )
        if pdf_file_element:
            self.safe_click(pdf_file_element, "Baptist Report PDF file")
        stoppable_sleep(1)

        # Confirm file selection
        pydirectinput.press("enter")
        stoppable_sleep(1)

        # Select 'Replace' option
        pydirectinput.press("left")
        stoppable_sleep(0.3)

        # Confirm replacement
        pydirectinput.press("enter")
        stoppable_sleep(3)

        # Extract text from PDF
        return self._extract_pdf_content()

    def _extract_pdf_content(self) -> str:
        """Extract text from saved PDF."""
        try:
            import PyPDF2

            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            pdf_path = os.path.join(desktop_path, self.PDF_FILENAME)

            if not os.path.exists(pdf_path):
                logger.error(f"[BAPTIST-BATCH] PDF not found: {pdf_path}")
                return "[ERROR] PDF file not found"

            with open(pdf_path, "rb") as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                text_content = []

                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(page_text)

                content = "\n".join(text_content)
                logger.info(f"[BAPTIST-BATCH] Extracted {len(content)} characters")
                return content

        except ImportError:
            return "[ERROR] PyPDF2 not installed"
        except Exception as e:
            return f"[ERROR] PDF extraction failed: {e}"

    def return_to_patient_list(self):
        """
        Return to patient list after extracting content.
        Uses Alt+F4 to close the patient detail view.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH] Returning to patient list...")

        # Click center to ensure focus
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait 5 seconds for the transition
        stoppable_sleep(5)
        logger.info("[BAPTIST-BATCH] Back at patient list")

    def cleanup(self):
        """Close Baptist EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[BAPTIST-BATCH] Cleanup - closing session...")

        try:
            self._baptist_flow.step_13_close_horizon()
            self._baptist_flow.step_14_accept_alert()
            self._baptist_flow.step_15_return_to_start()
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH] Cleanup error: {e}")

        logger.info("[BAPTIST-BATCH] Cleanup complete")

    def _warmup_omniparser(self):
        """Pre-heat OmniParser API."""
        if self._omniparser_warmed:
            return

        try:
            capturer = get_screen_capturer()
            omniparser = get_omniparser_client()
            data_url = capturer.capture_data_url()
            result = omniparser.parse_image(data_url)
            logger.info(
                f"[BAPTIST-BATCH] OmniParser warmed up - {len(result.elements)} elements"
            )
            self._omniparser_warmed = True
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH] Warmup failed: {e}")
