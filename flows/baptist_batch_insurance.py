"""
Baptist Batch Insurance Flow - Batch patient insurance extraction for Baptist Health.

Processes multiple patients in a single EMR session, extracting insurance
information from the Provider Face Sheet via PDF printing.
Uses BaptistInsuranceRunner with VDI OCR enhancement.
"""

import os
from datetime import datetime
from typing import List, Optional

import pyautogui
import pydirectinput

from config import config
from core.vdi_input import stoppable_sleep
from logger import logger

from .base_flow import BaseFlow
from .baptist import BaptistFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import BaptistInsuranceRunner


class BaptistBatchInsuranceFlow(BaseFlow):
    """
    Batch insurance flow for Baptist Health.

    Keeps the Baptist EMR session open while processing multiple patients,
    extracting insurance content via PDF printing from Provider Face Sheet,
    returning consolidated results.
    Uses BaptistInsuranceRunner with VDI OCR enhancement.
    """

    FLOW_NAME = "Baptist Batch Insurance"
    FLOW_TYPE = "baptist_batch_insurance"
    EMR_TYPE = "baptist"

    PDF_FILENAME = "baptis insurance.pdf"

    def __init__(self):
        super().__init__()
        self._baptist_flow = BaptistFlow()
        self._patient_detail_open = False  # Track if patient detail window is open
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
        self.hospital_type = hospital_type or "BAPTIST"
        self.results = []

        # Also setup the internal Baptist flow reference
        self._baptist_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )

        logger.info(f"[BAPTIST-BATCH-INS] Setup for {len(self.patient_names)} patients")

    def execute(self):
        """
        Execute batch insurance extraction.

        1. Navigate to patient list (once)
        2. Enter fullscreen mode (better for ROI masking)
        3. For each patient: find, extract insurance, return to list
        4. Exit fullscreen mode (only at the end)
        5. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" BAPTIST BATCH INSURANCE - STARTING")
        logger.info("=" * 70)
        logger.info(f"[BAPTIST-BATCH-INS] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self._navigate_to_patient_list():
            logger.error("[BAPTIST-BATCH-INS] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Enter fullscreen mode for better agentic vision and ROI masking
        logger.info("[BAPTIST-BATCH-INS] Entering fullscreen mode...")
        self._click_fullscreen()

        # Phase 2: Process each patient in fullscreen mode
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            self.current_patient = patient
            self.current_content = None

            logger.info(
                f"[BAPTIST-BATCH-INS] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self._find_patient(patient)

                if found:
                    # Extract insurance while still in fullscreen
                    self.current_content = self._extract_insurance()
                    logger.info(
                        f"[BAPTIST-BATCH-INS] Extracted insurance for {patient}"
                    )

                    # Close patient detail and return to list
                    self._return_to_patient_list()
                else:
                    logger.warning(f"[BAPTIST-BATCH-INS] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(
                    f"[BAPTIST-BATCH-INS] Error processing {patient}: {str(e)}"
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
        logger.info("[BAPTIST-BATCH-INS] Exiting fullscreen mode...")
        self._click_normalscreen()
        stoppable_sleep(3)  # Wait for screen to settle

        # Phase 3: Cleanup
        logger.info("[BAPTIST-BATCH-INS] Cleanup phase")
        self._cleanup()

        logger.info("=" * 70)
        logger.info(" BAPTIST BATCH INSURANCE - COMPLETE")
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
        Navigate to Baptist patient list.
        Reuses steps 1-10 from the standard Baptist flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH-INS] Navigating to patient list...")

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
            logger.info("[BAPTIST-BATCH-INS] Clicking patient list...")
            patient_list_btn = self._baptist_flow.wait_for_element(
                config.get_rpa_setting("images.patient_list"),
                timeout=10,
                description="Patient List button",
                auto_click=True,
            )
            if not patient_list_btn:
                raise Exception("Patient List not found")
            stoppable_sleep(3)

            logger.info("[BAPTIST-BATCH-INS] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[BAPTIST-BATCH-INS] Navigation failed: {e}")
            return False

    def _find_patient(self, patient_name: str) -> bool:
        """
        Find a patient and open their Face Sheet using the BaptistInsuranceRunner.
        Uses VDI OCR enhancement for better text detection.

        Returns:
            True if patient found and Face Sheet opened, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[BAPTIST-BATCH-INS] Finding patient: {patient_name}")

        # Use insurance runner with VDI enhancement
        runner = BaptistInsuranceRunner(
            max_steps=15,
            step_delay=1.5,
            vdi_enhance=True,
        )

        result = runner.run(patient_name=patient_name)

        # Track if patient detail is open (for cleanup if error)
        self._patient_detail_open = getattr(result, "patient_detail_open", False)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[BAPTIST-BATCH-INS] Patient not found: {patient_name}")
            return False

        # Check for other failures (error, stopped, max steps reached)
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not complete"
            logger.error(
                f"[BAPTIST-BATCH-INS] Agent error for {patient_name}: {error_msg}"
            )
            # If patient detail is open, we need to close it before continuing
            if self._patient_detail_open:
                logger.info("[BAPTIST-BATCH-INS] Closing patient detail after error...")
                self._close_patient_detail()
            return False

        logger.info(f"[BAPTIST-BATCH-INS] Patient found in {result.steps_taken} steps")
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
        logger.info("[BAPTIST-BATCH-INS] Patient detail closed")

    def _extract_insurance(self) -> str:
        """
        Extract insurance content via PDF printing from Face Sheet.
        Uses same flow as baptist_insurance.py phase 3.
        """
        self.set_step("EXTRACT_INSURANCE")
        logger.info(
            f"[BAPTIST-BATCH-INS] Extracting insurance for: {self.current_patient}"
        )

        # Step 1: Click print button
        logger.info("[BAPTIST-BATCH-INS] Step 1: Clicking print button...")
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

        # Step 2: Press Enter to confirm print
        logger.info("[BAPTIST-BATCH-INS] Step 2: Pressing Enter to confirm print...")
        pydirectinput.press("enter")
        stoppable_sleep(3)

        # Step 3: Ctrl+Alt to exit VDI focus (save dialog is on local machine)
        logger.info("[BAPTIST-BATCH-INS] Step 3: Exiting VDI focus with Ctrl+Alt...")
        pydirectinput.keyDown("ctrl")
        pydirectinput.keyDown("alt")
        pydirectinput.keyUp("alt")
        pydirectinput.keyUp("ctrl")
        stoppable_sleep(2)

        # Step 4: Click on Baptist Insurance document (existing file)
        logger.info(
            "[BAPTIST-BATCH-INS] Step 4: Clicking Baptist Insurance document..."
        )
        insurance_img = config.get_rpa_setting("images.baptist_insurance_btn")
        insurance_element = self.wait_for_element(
            insurance_img,
            timeout=10,
            confidence=0.95,
            description="Baptist Insurance document",
        )
        if insurance_element:
            self.safe_click(insurance_element, "Baptist Insurance document")
        else:
            logger.warning(
                "[BAPTIST-BATCH-INS] Baptist Insurance document not found, continuing..."
            )
        stoppable_sleep(2)

        # Step 5: Press Enter to confirm
        logger.info("[BAPTIST-BATCH-INS] Step 5: Pressing Enter to confirm...")
        pydirectinput.press("enter")
        stoppable_sleep(2)

        # Step 6: Left arrow to select 'Replace' option
        logger.info(
            "[BAPTIST-BATCH-INS] Step 6: Pressing Left arrow to select Replace..."
        )
        pydirectinput.press("left")
        stoppable_sleep(2)

        # Step 7: Enter to confirm replacement
        logger.info(
            "[BAPTIST-BATCH-INS] Step 7: Pressing Enter to confirm replacement..."
        )
        pydirectinput.press("enter")
        stoppable_sleep(5)  # Wait for PDF to be saved (increased from 3s)

        # Step 8: Extract text from PDF
        logger.info("[BAPTIST-BATCH-INS] Step 8: Extracting text from PDF...")
        return self._extract_pdf_content()

    def _extract_pdf_content(self) -> str:
        """Extract text from saved PDF with retry logic."""
        try:
            import PyPDF2

            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            pdf_path = os.path.join(desktop_path, self.PDF_FILENAME)

            if not os.path.exists(pdf_path):
                logger.error(f"[BAPTIST-BATCH-INS] PDF not found: {pdf_path}")
                return "[ERROR] PDF file not found"

            # Retry loop: wait for PDF to have content (max 5 attempts, 1s each)
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                file_size = os.path.getsize(pdf_path)
                if file_size > 0:
                    logger.info(f"[BAPTIST-BATCH-INS] PDF ready ({file_size} bytes)")
                    break
                logger.warning(
                    f"[BAPTIST-BATCH-INS] PDF empty, waiting... (attempt {attempt}/{max_attempts})"
                )
                stoppable_sleep(1)
            else:
                logger.error("[BAPTIST-BATCH-INS] PDF still empty after max attempts")
                return "[ERROR] PDF file is empty after waiting"

            with open(pdf_path, "rb") as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                text_content = []

                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(page_text)

                content = "\n".join(text_content)
                logger.info(f"[BAPTIST-BATCH-INS] Extracted {len(content)} characters")
                return content

        except ImportError:
            return "[ERROR] PyPDF2 not installed"
        except Exception as e:
            return f"[ERROR] PDF extraction failed: {e}"

    def _return_to_patient_list(self):
        """
        Close current patient detail and return to patient list.
        Uses Alt+F4 to close the patient detail view.
        Uses visual validation to confirm we're back at the patient list.
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[BAPTIST-BATCH-INS] Returning to patient list...")

        # Click center to ensure focus
        logger.info("[BAPTIST-BATCH-INS] Clicking center to ensure focus...")
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Close patient detail with Alt+F4
        logger.info("[BAPTIST-BATCH-INS] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for patient list header to be visible (visual validation)
        logger.info("[BAPTIST-BATCH-INS] Waiting for patient list header (max 30s)...")

        patient_list_header_img = config.get_rpa_setting(
            "images.baptist_patient_list_header"
        )

        header_found = self.wait_for_element(
            patient_list_header_img,
            timeout=30,
            description="Patient List Header",
        )

        if header_found:
            logger.info("[BAPTIST-BATCH-INS] OK - Patient list header detected")
        else:
            logger.warning(
                "[BAPTIST-BATCH-INS] Patient list header NOT detected - retrying Alt+F4..."
            )
            # Retry Alt+F4
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)
            pydirectinput.keyDown("alt")
            stoppable_sleep(0.1)
            pydirectinput.press("f4")
            stoppable_sleep(0.1)
            pydirectinput.keyUp("alt")

            # Wait again
            header_found = self.wait_for_element(
                patient_list_header_img,
                timeout=30,
                description="Patient List Header (retry)",
            )

            if header_found:
                logger.info(
                    "[BAPTIST-BATCH-INS] OK - Patient list header detected after retry"
                )
            else:
                logger.error(
                    "[BAPTIST-BATCH-INS] FAIL - Patient list header still NOT detected"
                )

        self._patient_detail_open = False
        logger.info("[BAPTIST-BATCH-INS] Back at patient list")

    def _cleanup(self):
        """Close Baptist EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[BAPTIST-BATCH-INS] Cleanup - closing session...")

        try:
            self._baptist_flow.step_13_close_horizon()
            self._baptist_flow.step_14_accept_alert()
            self._baptist_flow.step_15_return_to_start()
        except Exception as e:
            logger.warning(f"[BAPTIST-BATCH-INS] Cleanup error: {e}")

        logger.info("[BAPTIST-BATCH-INS] Cleanup complete")

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
