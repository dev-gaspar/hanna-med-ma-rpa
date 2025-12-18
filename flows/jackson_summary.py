"""
Jackson Summary Flow - Hybrid RPA + Agentic flow for patient summary retrieval.

This flow combines:
1. Traditional RPA to navigate to the patient list
2. Agentic brain (n8n) to find the specific patient's Final Report
3. Traditional RPA to copy content and close everything
"""

import threading
from datetime import datetime
from typing import Optional

import pyautogui
import pyperclip
import pydirectinput
import requests

from config import config
from core.s3_client import get_s3_client
from core.vdi_input import stoppable_sleep, type_with_clipboard
from logger import logger

from .base_flow import BaseFlow
from .jackson import JacksonFlow
from agentic import AgentRunner
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer


class JacksonSummaryFlow(BaseFlow):
    """
    Hybrid RPA flow for retrieving patient summary from Jackson Health.

    Workflow:
    1. Phase 1 (RPA): Navigate to patient list using existing Jackson flow steps
    2. Warmup: Pre-heat OmniParser API for faster agentic execution
    3. Phase 2 (Agentic): Use n8n brain to find and open patient's Final Report
    4. Phase 3 (RPA): Copy content, send to n8n for formatting, close everything
    """

    FLOW_NAME = "Jackson Patient Summary"
    FLOW_TYPE = "jackson_patient_summary"

    # Webhook URL for the Jackson Summary brain in n8n (for agentic phase)
    JACKSON_SUMMARY_BRAIN_URL = config.get_rpa_setting(
        "agentic.jackson_summary_brain_url"
    )

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()
        self.patient_name: Optional[str] = None
        self.copied_content: Optional[str] = None

        # Reference to Jackson flow for reusing navigation steps
        self._jackson_flow = JacksonFlow()

    def setup(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        patient_name=None,
    ):
        """Setup flow with execution context including patient name."""
        super().setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )
        self.patient_name = patient_name

        # Also setup the internal Jackson flow reference
        self._jackson_flow.setup(
            execution_id, sender, instance, trigger_type, doctor_name, credentials
        )

        logger.info(f"[JACKSON SUMMARY] Patient to find: {patient_name}")

    def execute(self):
        """Execute the hybrid flow for patient summary retrieval."""
        if not self.patient_name:
            raise ValueError("Patient name is required for summary flow")

        # Start warming up OmniParser in background WHILE Phase 1 runs
        warmup_thread = threading.Thread(target=self._warmup_omniparser, daemon=True)
        logger.info("[JACKSON SUMMARY] Starting OmniParser warmup in background...")
        warmup_thread.start()

        # Phase 1: Traditional RPA - Navigate to patient list
        logger.info("[JACKSON SUMMARY] Phase 1: Navigating to patient list...")
        self._phase1_navigate_to_patient_list()
        logger.info("[JACKSON SUMMARY] Phase 1: Complete - Patient list visible")

        # Wait for warmup to complete if still running
        if warmup_thread.is_alive():
            logger.info(
                "[JACKSON SUMMARY] Waiting for OmniParser warmup to complete..."
            )
            warmup_thread.join(timeout=60)  # Max 60 seconds
        logger.info("[JACKSON SUMMARY] OmniParser ready")

        # Phase 2: Agentic - Find the patient's Final Report
        logger.info(
            f"[JACKSON SUMMARY] Phase 2: Starting agentic search for '{self.patient_name}'..."
        )
        self._phase2_agentic_find_report()
        logger.info("[JACKSON SUMMARY] Phase 2: Complete - Report found")

        # Phase 3: Traditional RPA - Click report, copy content and close
        logger.info("[JACKSON SUMMARY] Phase 3a: Clicking on report document...")
        self._phase3_click_report_document()

        logger.info("[JACKSON SUMMARY] Phase 3b: Copying content...")
        self._phase3_copy_content()

        logger.info("[JACKSON SUMMARY] Phase 3c: Closing EMR...")
        self._phase3_close_and_cleanup()

        logger.info("[JACKSON SUMMARY] Complete - Content ready")

        return {
            "patient_name": self.patient_name,
            "content": self.copied_content,
        }

    def _phase1_navigate_to_patient_list(self):
        """
        Phase 1: Use traditional RPA to navigate to the patient list.
        Reuses steps 1-8 from the standard Jackson flow.
        """
        self.set_step("PHASE1_NAVIGATE_TO_PATIENT_LIST")

        # Reuse Jackson flow steps to get to patient list
        self._jackson_flow.step_1_tab()
        self._jackson_flow.step_2_powered()
        self._jackson_flow.step_3_open_download()
        self._jackson_flow.step_4_username()
        self._jackson_flow.step_5_password()
        self._jackson_flow.step_6_login_ok()
        self._jackson_flow.step_7_patient_list()
        self._jackson_flow.step_8_hospital_tab()

        # Give time for the patient list to fully load
        stoppable_sleep(3)

    def _warmup_omniparser(self):
        """
        Pre-heat the OmniParser API to reduce latency during agentic phase.
        Captures current screen and sends to OmniParser.
        """
        self.set_step("WARMUP_OMNIPARSER")

        try:
            capturer = get_screen_capturer()
            omniparser = get_omniparser_client()

            # Capture and parse current screen to warm up the API
            data_url = capturer.capture_data_url()
            parsed = omniparser.parse_image(data_url)

            logger.info(
                f"[JACKSON SUMMARY] OmniParser warmed up - detected {len(parsed.elements)} elements"
            )
        except Exception as e:
            logger.warning(f"[JACKSON SUMMARY] OmniParser warmup failed: {e}")
            # Continue anyway - not critical

    def _phase2_agentic_find_report(self):
        """
        Phase 2: Use the agentic brain to find and open the patient's Final Report.
        The n8n brain controls the navigation until it signals 'finish'.
        """
        self.set_step("PHASE2_AGENTIC_FIND_REPORT")

        # Build the goal for the agent
        goal = (
            f"Find and open the Final Report for patient '{self.patient_name}'. "
            f"Navigate through the patient list, search for the patient name, "
            f"click on their record, and open the Final Report tab. "
            f"Signal 'finish' when the Final Report content is visible."
        )

        # Create and run the agent with the Jackson Summary brain
        runner = AgentRunner(
            n8n_webhook_url=self.JACKSON_SUMMARY_BRAIN_URL,
            max_steps=30,  # Reasonable limit for finding a patient
            step_delay=1.5,  # Faster for simple navigation
        )

        result = runner.run(goal=goal)

        if result.status.value != "finished":
            raise Exception(
                f"Agentic phase failed: {result.error or 'Agent did not find the report'}"
            )

        logger.info(f"[JACKSON SUMMARY] Agent completed in {result.steps_taken} steps")

        # Give time for the report content to fully render
        stoppable_sleep(2)

    def _phase3_click_report_document(self):
        """
        Phase 3a: Click on the report document area to focus it for copying.
        The agent finished on the document view, we need to click on the document area.
        """
        self.set_step("PHASE3_CLICK_REPORT_DOCUMENT")
        logger.info("[JACKSON SUMMARY] Clicking on report document area...")

        # Try to find and click the report document image
        report_element = self.wait_for_element(
            config.get_rpa_setting("images.jackson_report_document"),
            timeout=10,
            description="Report Document",
        )

        if report_element:
            if not self.safe_click(report_element, "Report Document"):
                logger.warning(
                    "[JACKSON SUMMARY] Could not click report document, trying center screen"
                )
                # Fallback: click center of screen
                screen_w, screen_h = pyautogui.size()
                pyautogui.click(screen_w // 2, screen_h // 2)
        else:
            logger.warning(
                "[JACKSON SUMMARY] Report document image not found, clicking center"
            )
            # Fallback: click center of screen to focus document
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(screen_w // 2, screen_h // 2)

        stoppable_sleep(0.5)

    def _phase3_copy_content(self):
        """
        Phase 3b: Copy the content of the Final Report using keyboard shortcuts.
        """
        self.set_step("PHASE3_COPY_CONTENT")
        logger.info("[JACKSON SUMMARY] Copying report content...")

        # Clear clipboard first
        pyperclip.copy("")
        stoppable_sleep(0.3)

        # Select all content with Ctrl+A
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

        # Get the copied content
        self.copied_content = pyperclip.paste()

        if not self.copied_content or len(self.copied_content) < 50:
            logger.warning("[JACKSON SUMMARY] Copied content seems too short or empty")
        else:
            logger.info(
                f"[JACKSON SUMMARY] Copied {len(self.copied_content)} characters"
            )

    def _phase3_close_and_cleanup(self):
        """
        Phase 3c: Close Cerner patient detail and patient list windows, then return to VDI.

        Flow:
        1. Close patient detail view (first close click)
        2. Check if patient list is visible, if so close it too
        3. Navigate to VDI tab
        """
        self.set_step("PHASE3_CLOSE_AND_CLEANUP")
        logger.info("[JACKSON SUMMARY] Closing patient detail...")

        # Click on screen center to ensure window has focus
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # First close: Close the patient detail view with Alt+F4
        logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close patient detail...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for the window to close
        stoppable_sleep(5)

        # Click on screen center again to focus the next window
        pyautogui.click(screen_w // 2, screen_h // 2)
        stoppable_sleep(0.5)

        # Second close: Close the patient list/Jackson main window with Alt+F4
        logger.info("[JACKSON SUMMARY] Sending Alt+F4 to close Jackson...")
        pydirectinput.keyDown("alt")
        stoppable_sleep(0.1)
        pydirectinput.press("f4")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("alt")

        # Wait for the window to close
        stoppable_sleep(3)

        # Navigate to VDI desktop
        self._jackson_flow.step_11_vdi_tab()

    def notify_completion(self, result):
        """Notify n8n of successful completion with the copied content."""
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

    def run(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        patient_name=None,
    ):
        """
        Main entry point - runs the complete hybrid flow.
        Overrides parent to accept patient_name parameter.
        """
        from core.rpa_engine import set_should_stop
        from core.system_utils import keep_system_awake, allow_system_sleep
        from services.modal_watcher_service import (
            start_modal_watcher,
            stop_modal_watcher,
        )

        set_should_stop(False)
        self.setup(
            execution_id,
            sender,
            instance,
            trigger_type,
            doctor_name,
            credentials,
            patient_name,
        )

        logger.info("=" * 70)
        logger.info(f" STARTING {self.FLOW_NAME.upper()}")
        logger.info("=" * 70)
        logger.info(f"[INFO] Execution ID: {execution_id}")
        logger.info(f"[INFO] Patient Name: {patient_name}")
        logger.info(f"[INFO] Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)

        keep_system_awake()
        start_modal_watcher()
        self.verify_lobby()

        try:
            result = self.execute()
            self.notify_completion(result)

            print("\n" + "=" * 70)
            print(f" {self.FLOW_NAME.upper()} COMPLETED SUCCESSFULLY")
            print("=" * 70 + "\n")

        except KeyboardInterrupt:
            print(f"\n[STOP] {self.FLOW_NAME} Stopped by User")
            self.notify_error("RPA stopped by user")

        except Exception as e:
            print(f"\n[ERROR] {self.FLOW_NAME} Failed: {e}")
            self.notify_error(str(e))

        finally:
            stop_modal_watcher()
            allow_system_sleep()
            self.teardown()
            print("[INFO] System ready for new execution\n")
