"""
Jackson Summary Runner - Local orchestrator for patient summary extraction.

Replaces the n8n-based AgentRunner with local agents:
1. PatientFinderAgent - Find patient in list
2. RPA - Open patient, click Notes
3. ReportFinderAgent - Navigate tree to find report
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import config
from core.rpa_engine import check_should_stop, stoppable_sleep
from logger import logger

from agentic.emr.jackson.patient_finder import PatientFinderAgent
from agentic.emr.jackson.report_finder import ReportFinderAgent
from agentic.emr.jackson import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer


@dataclass
class RunnerResult:
    """Result from JacksonSummaryRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)


class JacksonSummaryRunner:
    """
    Local orchestrator for Jackson patient summary flow.

    Chains specialized agents:
    1. PatientFinderAgent - Finds patient element
    2. RPA actions - Opens patient and Notes
    3. ReportFinderAgent - Navigates to report
    """

    def __init__(
        self,
        max_steps: int = 30,
        step_delay: float = 1.5,
    ):
        self.max_steps = max_steps
        self.step_delay = step_delay

        # Components
        self.omniparser = get_omniparser_client()
        self.capturer = get_screen_capturer()
        self.patient_finder = PatientFinderAgent()
        self.report_finder = ReportFinderAgent()

        # State
        self.execution_id = ""
        self.history: List[Dict[str, Any]] = []
        self.current_step = 0

    def run(self, patient_name: str) -> RunnerResult:
        """
        Run the full flow to find patient report.

        Args:
            patient_name: Name of patient to find

        Returns:
            RunnerResult with outcome
        """
        self.execution_id = str(uuid.uuid4())[:8]
        self.history = []
        self.current_step = 0

        logger.info("=" * 70)
        logger.info(" LOCAL JACKSON RUNNER - STARTING")
        logger.info("=" * 70)
        logger.info(f"[RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[RUNNER] Patient: {patient_name}")
        logger.info("=" * 70)

        try:
            # === PHASE 1: Find Patient (with retry for OCR failures) ===
            logger.info("[RUNNER] Phase 1: Finding patient...")
            max_retries = 3
            patient_result = None

            for attempt in range(1, max_retries + 1):
                patient_result = self._phase1_find_patient(patient_name)

                if patient_result.status == "found":
                    break
                elif patient_result.status == "retry":
                    logger.info(
                        f"[RUNNER] Retry {attempt}/{max_retries} - OCR didn't detect patient, retrying..."
                    )
                    stoppable_sleep(1.5)
                    continue
                else:  # not_found
                    break

            if patient_result.status == "not_found" or (
                patient_result.status == "retry" and attempt == max_retries
            ):
                logger.warning("[RUNNER] Patient not found in list")
                return RunnerResult(
                    status=AgentStatus.PATIENT_NOT_FOUND,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Patient '{patient_name}' not found",
                    history=self.history,
                )

            patient_element_id = patient_result.element_id
            logger.info(
                f"[RUNNER] Phase 1 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 2: Open Patient + Notes (RPA) ===
            logger.info("[RUNNER] Phase 2: Opening patient record...")
            self._phase2_open_patient_and_notes(patient_element_id)
            logger.info("[RUNNER] Phase 2 complete - Notes view open")

            # === PHASE 3: Find Report (Agent Loop) ===
            logger.info("[RUNNER] Phase 3: Navigating to report...")
            report_found = self._phase3_find_report()

            if not report_found:
                return RunnerResult(
                    status=AgentStatus.ERROR,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error="Could not find report within max steps",
                    history=self.history,
                )

            logger.info("=" * 70)
            logger.info(" LOCAL JACKSON RUNNER - FINISHED")
            logger.info(f" Steps: {self.current_step}")
            logger.info("=" * 70)

            return RunnerResult(
                status=AgentStatus.FINISHED,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                history=self.history,
            )

        except Exception as e:
            logger.error(f"[RUNNER] Error: {e}", exc_info=True)
            return RunnerResult(
                status=AgentStatus.ERROR,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                error=str(e),
                history=self.history,
            )

    def _phase1_find_patient(self, patient_name: str):
        """Phase 1: Use PatientFinderAgent to locate patient."""
        self.current_step += 1

        # Capture and parse screen
        parsed = self.omniparser.parse_screen()
        image_b64 = self._get_image_base64_from_parsed(parsed)
        elements = self._elements_to_dicts(parsed.elements)

        # Run agent
        result = self.patient_finder.find_patient(
            patient_name=patient_name,
            image_base64=image_b64,
            ui_elements=elements,
        )

        self._record_step("patient_finder", result.status, result.reasoning)
        return result

    def _phase2_open_patient_and_notes(self, element_id: int):
        """Phase 2: RPA to open patient and click Notes."""
        import pyautogui

        self.current_step += 1

        # Get current elements for clicking
        parsed = self.omniparser.parse_screen()
        elements = self._elements_to_dicts(parsed.elements)

        # Double-click patient
        result = tools.click_element(element_id, elements, action="dblclick")
        self._record_step(
            "rpa",
            "dblclick_patient",
            f"Double-clicked patient element {element_id}: {result}",
        )

        # Wait for patient detail to load
        logger.info("[RUNNER] Waiting 5s for patient detail...")
        stoppable_sleep(5)
        check_should_stop()

        # Press Enter to dismiss any potential modal/alert
        self.current_step += 1
        pyautogui.press("enter")
        logger.info("[RUNNER] Pressed Enter to dismiss potential modal")
        self._record_step("rpa", "press_enter", "Pressed Enter to dismiss modal")

        # Wait after Enter
        logger.info("[RUNNER] Waiting 5s after Enter...")
        stoppable_sleep(5)
        check_should_stop()

        # Click Notes menu using image
        self.current_step += 1
        notes_image = config.get_rpa_setting("images.jackson_notes_menu")
        try:
            location = pyautogui.locateOnScreen(notes_image, confidence=0.8)
            if location:
                pyautogui.click(pyautogui.center(location))
                logger.info("[RUNNER] Clicked Notes menu")
                self._record_step("rpa", "click_notes", "Clicked Notes menu: success")
            else:
                logger.warning("[RUNNER] Notes menu not found on screen")
                self._record_step("rpa", "click_notes", "Notes menu not found")
        except Exception as e:
            logger.error(f"[RUNNER] Error clicking Notes: {e}")
            self._record_step("rpa", "click_notes", f"Error: {e}")

        # Wait for notes tree to load
        logger.info("[RUNNER] Waiting 5s for notes tree...")
        stoppable_sleep(5)
        check_should_stop()

    def _phase3_find_report(self) -> bool:
        """Phase 3: Use ReportFinderAgent in a loop until report found."""

        while self.current_step < self.max_steps:
            check_should_stop()
            self.current_step += 1

            logger.info(f"[RUNNER] Step {self.current_step}/{self.max_steps}")

            # Capture and parse
            parsed = self.omniparser.parse_screen()
            image_b64 = self._get_image_base64_from_parsed(parsed)
            elements = self._elements_to_dicts(parsed.elements)

            # Get agent decision
            result = self.report_finder.decide_action(
                image_base64=image_b64,
                ui_elements=elements,
                history=self.history[-10:],
            )

            self._record_step(
                "report_finder", result.action or result.status, result.reasoning
            )

            # Check if finished
            if result.status == "finished":
                logger.info("[RUNNER] Report found!")
                return True

            if result.status == "error":
                logger.error(f"[RUNNER] Agent error: {result.reasoning}")
                return False

            # Execute action
            self._execute_action(result.action, result.target_id, elements)

            # Delay before next step
            stoppable_sleep(self.step_delay)

        logger.warning("[RUNNER] Max steps reached without finding report")
        return False

    def _execute_action(self, action: str, target_id: Optional[int], elements: list):
        """Execute the action decided by the agent."""
        if action == "nav_up":
            tools.nav_up()
        elif action == "nav_down":
            tools.nav_down()
        elif action == "click" and target_id is not None:
            tools.click_element(target_id, elements, action="click")
        elif action == "dblclick" and target_id is not None:
            tools.click_element(target_id, elements, action="dblclick")
        elif action == "wait":
            logger.info("[RUNNER] Waiting...")
            stoppable_sleep(1)
        else:
            logger.warning(f"[RUNNER] Unknown action: {action}")

    def _record_step(self, agent: str, action: str, reasoning: str):
        """Record a step in history."""
        self.history.append(
            {
                "step": self.current_step,
                "agent": agent,
                "action": action,
                "reasoning": reasoning,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def _get_image_base64_from_parsed(self, parsed) -> str:
        """Extract base64 image from parsed screen or capture new one."""
        # The labeled_image_url is a data URL, extract base64
        if parsed.labeled_image_url and parsed.labeled_image_url.startswith("data:"):
            parts = parsed.labeled_image_url.split(",", 1)
            if len(parts) == 2:
                return parts[1]

        # Fallback: capture new screenshot
        return self.capturer.capture_base64()

    def _elements_to_dicts(self, elements) -> List[Dict[str, Any]]:
        """Convert UIElement objects to dictionaries."""
        return [
            {
                "id": el.id,
                "type": el.type,
                "content": el.content,
                "center": list(el.center),
                "bbox": el.bbox,
            }
            for el in elements
        ]
