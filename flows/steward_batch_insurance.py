"""
Steward Batch Insurance Flow - Batch patient insurance extraction for Steward Health.

Processes multiple patients in a single EMR session, extracting insurance
information from the Administrative > Demographics > Insurance screen.
Uses StewardInsuranceRunner for patient finding.
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
from .steward import StewardFlow
from agentic.models import AgentStatus
from agentic.omniparser_client import start_warmup_async
from agentic.runners import StewardInsuranceRunner


class StewardBatchInsuranceFlow(BaseFlow):
    """
    Batch insurance flow for Steward Health.

    Keeps the Steward EMR session open while processing multiple patients,
    extracting insurance content from Administrative > Demographics > Insurance,
    returning consolidated results.

    Flow:
    1. Navigate to patient list (Rounds Patients)
    2. For each patient:
       - Find patient using StewardInsuranceRunner (agentic)
       - Navigate to Administrative > Demographics > Insurance > General
       - Ctrl+A, Ctrl+C to copy content
    3. Cleanup (close EMR, return to VDI)
    """

    FLOW_NAME = "Steward Batch Insurance"
    FLOW_TYPE = "steward_batch_insurance"
    EMR_TYPE = "steward"

    def __init__(self):
        super().__init__()
        self._steward_flow = StewardFlow()
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
        self.hospital_type = hospital_type or "STEWARD"
        self.results = []

        # Also setup the internal Steward flow reference
        self._steward_flow.setup(
            self.execution_id,
            self.sender,
            self.instance,
            self.trigger_type,
            self.doctor_name,
            self.credentials,
        )

        logger.info(f"[STEWARD-BATCH-INS] Setup for {len(self.patient_names)} patients")

    def execute(self):
        """
        Execute batch insurance extraction.

        1. Navigate to patient list (once)
        2. For each patient: find, extract insurance
        3. Cleanup (once)
        """
        logger.info("=" * 70)
        logger.info(" STEWARD BATCH INSURANCE - STARTING")
        logger.info("=" * 70)
        logger.info(f"[STEWARD-BATCH-INS] Patients to process: {self.patient_names}")
        logger.info("=" * 70)

        # Phase 1: Navigate to patient list (once)
        if not self._navigate_to_patient_list():
            logger.error("[STEWARD-BATCH-INS] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Phase 2: Process each patient
        total_patients = len(self.patient_names)
        for idx, patient in enumerate(self.patient_names, 1):
            self.current_patient = patient
            self.current_content = None

            logger.info(
                f"[STEWARD-BATCH-INS] Processing patient {idx}/{total_patients}: {patient}"
            )

            try:
                found = self._find_patient(patient)

                if found:
                    # Extract insurance content
                    self.current_content = self._extract_insurance()
                    logger.info(
                        f"[STEWARD-BATCH-INS] Extracted insurance for {patient}"
                    )

                    # Return to patient list
                    self._return_to_patient_list()
                else:
                    logger.warning(f"[STEWARD-BATCH-INS] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(
                    f"[STEWARD-BATCH-INS] Error processing {patient}: {str(e)}"
                )
                self.results.append(
                    {
                        "patient": patient,
                        "found": False,
                        "content": None,
                        "error": str(e),
                    }
                )
                # Try to recover
                if self._patient_detail_open:
                    try:
                        self._return_to_patient_list()
                    except Exception:
                        pass

        # Phase 3: Cleanup
        logger.info("[STEWARD-BATCH-INS] Cleanup phase")
        self._cleanup()

        logger.info("=" * 70)
        logger.info(" STEWARD BATCH INSURANCE - COMPLETE")
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
        Navigate to Steward patient list.
        Reuses steps 1-6 from the standard Steward flow.
        """
        self.set_step("NAVIGATE_TO_PATIENT_LIST")
        logger.info("[STEWARD-BATCH-INS] Navigating to patient list...")

        try:
            # Start OmniParser warmup in background
            start_warmup_async()

            # Reuse Steward flow steps
            self._steward_flow.step_1_tab()
            self._steward_flow.step_2_favorite()
            self._steward_flow.step_3_meditech()
            self._steward_flow.step_4_login()
            self._steward_flow.step_5_open_session()
            self._steward_flow.step_6_navigate_menu_5()

            # Wait for patient list to be visible
            logger.info("[STEWARD-BATCH-INS] Waiting for patient list to load...")
            menu = self._steward_flow.robust_wait_for_element(
                config.get_rpa_setting("images.steward_load_menu_6"),
                target_description="Menu (step 6) - Patient list visible",
                handlers=self._steward_flow._get_sign_list_handlers(),
                timeout=config.get_timeout("steward.menu"),
            )

            if not menu:
                raise Exception("Patient list not visible")

            stoppable_sleep(2)
            logger.info("[STEWARD-BATCH-INS] Patient list visible")
            return True

        except Exception as e:
            logger.error(f"[STEWARD-BATCH-INS] Navigation failed: {e}")
            return False

    def _find_patient(self, patient_name: str) -> bool:
        """
        Find a patient using the StewardInsuranceRunner.

        Returns:
            True if patient found and clicked, False otherwise.
        """
        self.set_step(f"FIND_PATIENT_{patient_name}")
        logger.info(f"[STEWARD-BATCH-INS] Finding patient: {patient_name}")

        runner = StewardInsuranceRunner(
            max_steps=15,
            step_delay=1.5,
        )

        result = runner.run(patient_name=patient_name)

        # Track if patient detail is open (for cleanup if error)
        self._patient_detail_open = getattr(result, "patient_detail_open", False)

        # Check if patient was not found
        if result.status == AgentStatus.PATIENT_NOT_FOUND:
            logger.warning(f"[STEWARD-BATCH-INS] Patient not found: {patient_name}")
            return False

        # Check for other failures
        if result.status != AgentStatus.FINISHED:
            error_msg = result.error or "Agent did not complete"
            logger.error(
                f"[STEWARD-BATCH-INS] Agent error for {patient_name}: {error_msg}"
            )
            return False

        self._patient_detail_open = True
        logger.info(f"[STEWARD-BATCH-INS] Patient found in {result.steps_taken} steps")
        stoppable_sleep(2)
        return True

    def _extract_insurance(self) -> str:
        """
        Extract insurance content from Administrative > Demographics > Insurance.

        Flow:
        1. Click Administrative Tab
        2. Click Administrative menu item
        3. Click Demographics
        4. Click Insurance
        5. Click General to focus
        6. Ctrl+A, Ctrl+C to copy content
        """
        self.set_step("EXTRACT_INSURANCE")
        logger.info(
            f"[STEWARD-BATCH-INS] Extracting insurance for: {self.current_patient}"
        )

        # Step 1: Click Administrative Tab
        logger.info("[STEWARD-BATCH-INS] Step 1: Clicking Administrative Tab...")
        tab_admin_img = config.get_rpa_setting(
            "images.steward_insurance_tab_administrative"
        )
        location = self.wait_for_element(
            tab_admin_img,
            timeout=15,
            confidence=0.8,
            description="Administrative Tab",
        )
        if not location:
            raise Exception("Administrative Tab not found")
        self.safe_click(location, "Administrative Tab")
        stoppable_sleep(3)

        # Step 2: Click Administrative menu item
        logger.info("[STEWARD-BATCH-INS] Step 2: Clicking Administrative menu item...")
        admin_img = config.get_rpa_setting("images.steward_insurance_administrative")
        location = self.wait_for_element(
            admin_img,
            timeout=15,
            confidence=0.8,
            description="Administrative menu",
        )
        if not location:
            raise Exception("Administrative menu not found")
        self.safe_click(location, "Administrative menu")
        stoppable_sleep(2)

        # Step 3: Click Demographics
        logger.info("[STEWARD-BATCH-INS] Step 3: Clicking Demographics...")
        demographics_img = config.get_rpa_setting(
            "images.steward_insurance_demographics"
        )
        location = self.wait_for_element(
            demographics_img,
            timeout=15,
            confidence=0.8,
            description="Demographics",
        )
        if not location:
            raise Exception("Demographics not found")
        self.safe_click(location, "Demographics")
        stoppable_sleep(2)

        # Step 4 & 5: Click Insurance and Verify with General (Retry Logic)
        logger.info("[STEWARD-BATCH-INS] Step 4: Clicking Insurance...")
        insurance_img = config.get_rpa_setting("images.steward_insurance_insurance")
        general_img = config.get_rpa_setting("images.steward_insurance_general")

        max_retries = 1
        for attempt in range(max_retries + 1):
            # Click Insurance
            location = self.wait_for_element(
                insurance_img,
                timeout=15,
                confidence=0.8,
                description="Insurance",
            )
            if not location:
                raise Exception("Insurance button not found")
            self.safe_click(location, "Insurance")
            stoppable_sleep(2)

            # Check for General (Verification)
            logger.info(
                f"[STEWARD-BATCH-INS] Step 5: Waiting for General (Attempt {attempt+1})..."
            )
            # Generous timeout as requested to avoid false negatives
            location = self.wait_for_element(
                general_img,
                timeout=20,
                confidence=0.8,
                description="General",
            )

            if location:
                # Found it! Click to focus and break loop
                logger.info(
                    "[STEWARD-BATCH-INS] General tab found, clicking to focus..."
                )
                self.safe_click(location, "General")
                stoppable_sleep(2)
                break
            else:
                if attempt < max_retries:
                    logger.warning(
                        "[STEWARD-BATCH-INS] General tab not found, retrying Insurance click..."
                    )
                else:
                    raise Exception("General tab not found after retry")

        # Step 6: Clear clipboard and Select All + Copy
        logger.info("[STEWARD-BATCH-INS] Step 6: Selecting all and copying content...")
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
        logger.info(f"[STEWARD-BATCH-INS] Copied {len(content)} characters")

        return content or ""

    def _return_to_patient_list(self):
        """
        Close current patient and return to patient list.
        Uses single click on Close Meditech (acting as Return).
        """
        self.set_step("RETURN_TO_PATIENT_LIST")
        logger.info("[STEWARD-BATCH-INS] Returning to patient list...")

        try:
            # Click somewhere neutral first (as requested)
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)
            stoppable_sleep(0.5)

            # Single click on Close Meditech to return to list
            # We don't use step_15 because it clicks multiple times to close the app
            logger.info(
                "[STEWARD-BATCH-INS] Clicking Close Meditech (once) to return..."
            )
            close_btn = self.wait_for_element(
                config.get_rpa_setting("images.steward_close_meditech"),
                timeout=config.get_timeout("steward.close_meditech"),
                description="Close Meditech (Return)",
            )

            if close_btn:
                self.safe_click(close_btn, "Close Meditech (Return)")
                # Move mouse away to avoid hover state affecting next detection
                pyautogui.moveTo(screen_w // 2, screen_h // 2)
                stoppable_sleep(2)
            else:
                logger.warning("[STEWARD-BATCH-INS] Close button not found!")

            # Wait for patient list to be visible again
            # Using handlers to manage Sign List popup if it appears
            menu = self._steward_flow.robust_wait_for_element(
                config.get_rpa_setting("images.steward_load_menu_6"),
                target_description="Menu (step 6) - Patient list",
                handlers=self._steward_flow._get_sign_list_handlers(),
                timeout=15,
            )

            if menu:
                logger.info("[STEWARD-BATCH-INS] OK - Back at patient list")
                self._patient_detail_open = False
            else:
                logger.warning(
                    "[STEWARD-BATCH-INS] Could not confirm patient list visibility"
                )

        except Exception as e:
            logger.warning(f"[STEWARD-BATCH-INS] Return to list error: {e}")

    def _cleanup(self):
        """Close Steward EMR session completely."""
        self.set_step("CLEANUP")
        logger.info("[STEWARD-BATCH-INS] Cleanup - closing EMR...")

        try:
            # Use Steward cleanup steps
            self._steward_flow.step_15_close_meditech()
            self._steward_flow.step_16_tab_logged_out()
            self._steward_flow.step_17_close_tab_final()
            self._steward_flow.step_18_url()
            self._steward_flow.step_19_vdi_tab()

        except Exception as e:
            logger.warning(f"[STEWARD-BATCH-INS] Cleanup error: {e}")
            # Try to at least get back to lobby
            self.verify_lobby()

        logger.info("[STEWARD-BATCH-INS] Cleanup complete")

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
