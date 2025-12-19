"""
Baptist Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Agentic brain (n8n) to find the specific patient across hospital tabs
3. Traditional RPA to close everything

Note: Content is returned as dummy since Baptist VDI doesn't allow clipboard access.
"""

import threading
from datetime import datetime
from typing import Optional

import pyautogui

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
    4. Phase 3 (RPA): Close patient detail and cleanup

    Note: Content is returned as dummy since Baptist VDI doesn't allow clipboard access.
    """

    FLOW_NAME = "Baptist Patient Summary"
    FLOW_TYPE = "baptist_patient_summary"

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

        # Phase 3: Close and cleanup
        logger.info("[BAPTIST SUMMARY] Phase 3: Closing patient detail and cleanup...")
        self._phase3_close_and_cleanup()

        logger.info("[BAPTIST SUMMARY] Complete")

        # Return dummy content (Baptist VDI doesn't allow clipboard access)
        return {
            "patient_name": self.patient_name,
            "content": f"[DUMMY CONTENT] Summary for patient: {self.patient_name}. Baptist VDI clipboard not accessible.",
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

    def _phase3_close_and_cleanup(self):
        """
        Phase 3: Close patient detail and perform standard cleanup.

        Flow:
        1. Close patient detail view with Alt+F4
        2. Use Baptist cleanup steps (12-15)
        """
        # Close patient detail window
        logger.info("[BAPTIST SUMMARY] Closing patient detail with Alt+F4...")
        pyautogui.hotkey("alt", "f4")
        stoppable_sleep(2)

        # Reuse Baptist cleanup steps
        self._baptist_flow.step_12_close_powerchart()
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
