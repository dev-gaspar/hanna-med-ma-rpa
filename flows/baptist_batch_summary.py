"""
Baptist Batch Summary Flow - Batch patient summary for Baptist Health.

Extends BaseBatchSummaryFlow to provide Baptist-specific implementation.
Keeps EMR session open while processing multiple patients via PDF extraction.
Uses local BaptistSummaryRunner with VDI OCR enhancement.
"""

import os
from typing import Optional

import pyautogui
import pydirectinput

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_batch_summary import BaseBatchSummaryFlow
from .baptist import BaptistFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client, start_warmup_async
from agentic.screen_capturer import get_screen_capturer
from agentic.runners import BaptistSummaryRunner


class BaptistBatchSummaryFlow(BaseBatchSummaryFlow):
    """
    Batch summary flow for Baptist Health.

    Keeps the Baptist EMR session open while processing multiple patients,
    extracting content via PDF printing, returning consolidated results.
    Uses local BaptistSummaryRunner with VDI OCR enhancement.
    """

    FLOW_NAME = "Baptist Batch Summary"
    FLOW_TYPE = "baptist_batch_summary"

    PDF_FILENAME = "baptis report.pdf"

    def __init__(self):
        super().__init__()
        self._baptist_flow = BaptistFlow()
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

    def execute(self):
        """
        Override base execute to add fullscreen handling and proper timing.

        1. Navigate to patient list (once)
        2. Enter fullscreen mode (better for ROI masking)
        3. For each patient: find, extract, return to list
        4. Exit fullscreen mode (only at the end)
        5. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" BAPTIST BATCH SUMMARY - STARTING")
        logger.info("=" * 70)
        logger.info(f"[BAPTIST-BATCH] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self.navigate_to_patient_list():
            logger.error("[BAPTIST-BATCH] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Enter fullscreen mode for better agentic vision and ROI masking
        logger.info("[BAPTIST-BATCH] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Process each patient in fullscreen mode
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            is_last_patient = idx == total_patients
            self.current_patient = patient
            self.current_content = None

            logger.info(
                f"[BAPTIST-BATCH] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self.find_patient(patient)

                if found:
                    # Extract content while still in fullscreen
                    self.current_content = self.extract_content()
                    logger.info(f"[BAPTIST-BATCH] Extracted content for {patient}")

                    # Close patient detail and return to list
                    # (unless this is the last patient - we'll handle that in cleanup)
                    if not is_last_patient:
                        self.return_to_patient_list()
                    else:
                        # For last patient, just mark that detail is open
                        self._patient_detail_open = True
                        logger.info(
                            "[BAPTIST-BATCH] Last patient - keeping detail open for cleanup"
                        )
                else:
                    logger.warning(f"[BAPTIST-BATCH] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(f"[BAPTIST-BATCH] Error processing {patient}: {str(e)}")
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
        logger.info("[BAPTIST-BATCH] Exiting fullscreen mode...")
        self._click_normalscreen()
        stoppable_sleep(3)  # Wait for screen to settle

        # Phase 3: Cleanup
        logger.info("[BAPTIST-BATCH] Cleanup phase")
        self.cleanup()

        logger.info("=" * 70)
        logger.info(" BAPTIST BATCH SUMMARY - COMPLETE")
        logger.info(f" Processed: {total_patients} patients")
        logger.info(f" Found: {sum(1 for r in self.results if r.get('found'))}")
        logger.info("=" * 70)

        return {
            "patients": self.results,
            "hospital": self.hospital_type,
            "total": len(self.patient_names),
            "found_count": sum(1 for r in self.results if r.get("found")),
        }

    def _click_fullscreen(self):
        """Click fullscreen button for better visualization during agentic phase."""
        self.set_step("CLICK_FULLSCREEN")
        fullscreen_img = config.get_rpa_setting("images.baptist_fullscreen_btn")
        try:
            location = pyautogui.locateOnScreen(fullscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[BAPTIST-BATCH] Clicked fullscreen button")
                stoppable_sleep(2)
            else:
                logger.warning(
                    "[BAPTIST-BATCH] Fullscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH] Error clicking fullscreen: {e}")

    def _click_normalscreen(self):
        """Click normalscreen button to restore view before cleanup."""
        self.set_step("CLICK_NORMALSCREEN")
        normalscreen_img = config.get_rpa_setting("images.baptist_normalscreen_btn")
        try:
            location = pyautogui.locateOnScreen(normalscreen_img, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[BAPTIST-BATCH] Clicked normalscreen button")
                stoppable_sleep(2)
            else:
                logger.warning(
                    "[BAPTIST-BATCH] Normalscreen button not found - continuing"
                )
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH] Error clicking normalscreen: {e}")

    def navigate_to_patient_list(self) -> bool:
        """
        Navigate to Baptist patient list.
        Reuses steps 1-10 from the standard Baptist flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH] Navigating to patient list...")

        try:
            # Start OmniParser warmup in background
            start_warmup_async()

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

            logger.info("[BAPTIST-BATCH] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[BAPTIST-BATCH] Navigation failed: {e}")
            return False

    def find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the local BaptistSummaryRunner.
        Uses VDI OCR enhancement for better text detection.

        Returns:
            True if patient found and report opened, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[BAPTIST-BATCH] Finding patient: {patient_name}")

        # Use local runner with VDI enhancement
        runner = BaptistSummaryRunner(
            max_steps=30,
            step_delay=1,
            vdi_enhance=True,
        )

        result = runner.run(patient_name=patient_name)

        # Track if patient detail is open (for cleanup if error)
        self._patient_detail_open = getattr(result, "patient_detail_open", False)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[BAPTIST-BATCH] Patient not found: {patient_name}")
            return False

        # Check for other failures (error, stopped, max steps reached)
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not find the report"
            logger.error(f"[BAPTIST-BATCH] Agent error for {patient_name}: {error_msg}")
            # If patient detail is open, we need to close it before continuing
            if self._patient_detail_open:
                logger.info("[BAPTIST-BATCH] Closing patient detail after error...")
                self._close_patient_detail()
            return False

        logger.info(f"[BAPTIST-BATCH] Patient found in {result.steps_taken} steps")
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

        stoppable_sleep(5)
        self._patient_detail_open = False
        logger.info("[BAPTIST-BATCH] Patient detail closed")

    def extract_content(self) -> str:
        """
        Extract content via PDF printing and text extraction.
        Uses 2-second delays after each action for VDI modal stability.
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
        stoppable_sleep(2)

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
        stoppable_sleep(2)
        pydirectinput.press("enter")
        stoppable_sleep(4)  # Extra wait for save dialog

        # Exit VDI focus (Ctrl+Alt)
        pydirectinput.keyDown("ctrl")
        pydirectinput.keyDown("alt")
        pydirectinput.keyUp("alt")
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(2)

        # Click existing PDF file to select
        pdf_file_element = self.wait_for_element(
            config.get_rpa_setting("images.baptist_report_pdf"),
            timeout=10,
            description="Baptist Report PDF file",
        )
        if pdf_file_element:
            self.safe_click(pdf_file_element, "Baptist Report PDF file")
        stoppable_sleep(2)

        # Confirm file selection
        pydirectinput.press("enter")
        stoppable_sleep(2)

        # Select 'Replace' option
        pydirectinput.press("left")
        stoppable_sleep(2)

        # Confirm replacement
        pydirectinput.press("enter")
        stoppable_sleep(3)  # Wait for PDF to save

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
        Close current patient detail and return to patient list.
        Uses Alt+F4 to close the patient detail view.
        Uses visual validation to confirm we're back at the patient list.
        Includes fallback: if report document is still visible, retry Alt+F4.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH] Returning to patient list...")

        # Click center to ensure focus
        logger.info("[BAPTIST-BATCH] Clicking center to ensure focus...")
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        logger.info("[BAPTIST-BATCH] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for patient list header to be visible (visual validation)
        logger.info("[BAPTIST-BATCH] Waiting for patient list header (max 30s)...")

        patient_list_header_img = config.get_rpa_setting(
            "images.baptist_patient_list_header"
        )
        report_document_img = config.get_rpa_setting("images.baptist_report_document")

        header_found = self.wait_for_element(
            patient_list_header_img,
            timeout=30,
            description="Patient List Header",
        )

        if header_found:
            logger.info("[BAPTIST-BATCH] OK - Patient list header detected")
        else:
            # Fallback: if header not found, check if report document is still visible
            logger.warning(
                "[BAPTIST-BATCH] FAIL - Patient list header NOT detected after 30s"
            )
            logger.info(
                "[BAPTIST-BATCH] Checking if report document is still visible..."
            )

            # Check if report document is still visible (patient detail still open)
            try:
                report_visible = pyautogui.locateOnScreen(
                    report_document_img, confidence=0.8
                )
            except Exception:
                report_visible = None

            if report_visible:
                logger.warning(
                    "[BAPTIST-BATCH] Report document still visible - patient detail NOT closed"
                )
                logger.info(
                    "[BAPTIST-BATCH] Retrying - clicking center to ensure focus..."
                )

                # Click center to ensure focus
                pyautogui.click(screen_w // 2, screen_h // 2)
                stoppable_sleep(0.5)

                # Retry Alt+F4
                logger.info("[BAPTIST-BATCH] Sending Alt+F4 again...")
                pydirectinput.keyDown("alt")
                stoppable_sleep(0.1)
                pydirectinput.press("f4")
                stoppable_sleep(0.1)
                pydirectinput.keyUp("alt")

                # Wait for patient list header again
                logger.info(
                    "[BAPTIST-BATCH] Waiting for patient list header after retry (max 30s)..."
                )
                header_found = self.wait_for_element(
                    patient_list_header_img,
                    timeout=30,
                    description="Patient List Header (retry)",
                )

                if header_found:
                    logger.info(
                        "[BAPTIST-BATCH] OK - Patient list header detected after retry"
                    )
                else:
                    logger.error(
                        "[BAPTIST-BATCH] FAIL - Patient list header still NOT detected after retry"
                    )
            else:
                logger.info(
                    "[BAPTIST-BATCH] Report document not visible - assuming we're at patient list"
                )

        self._patient_detail_open = False
        logger.info("[BAPTIST-BATCH] Back at patient list")

    def cleanup(self):
        """Close Baptist EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[BAPTIST-BATCH] Cleanup - closing session...")

        # If patient detail is still open (last patient), close it first
        if self._patient_detail_open:
            logger.info("[BAPTIST-BATCH] Closing last patient detail...")
            self._close_patient_detail()

        try:
            self._baptist_flow.step_13_close_horizon()
            self._baptist_flow.step_14_accept_alert()
            self._baptist_flow.step_15_return_to_start()
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH] Cleanup error: {e}")

        logger.info("[BAPTIST-BATCH] Cleanup complete")
