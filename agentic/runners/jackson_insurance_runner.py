"""
Jackson Insurance Runner - Local orchestrator for patient insurance extraction.

Replaces the n8n-based AgentRunner with local agents:
1. PatientFinderAgent - Find patient in list
2. RPA - Open patient and handle modals
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyautogui

from config import config
from core.rpa_engine import RPABotBase
from logger import logger

from agentic.emr.jackson.patient_finder import PatientFinderAgent
from agentic.emr.jackson import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer, get_agent_rois
from version import __version__


@dataclass
class RunnerResult:
    """Result from JacksonInsuranceRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    patient_detail_open: bool = (
        False  # True if patient detail window is open (for cleanup)
    )


class JacksonInsuranceRunner:
    """
    Local orchestrator for Jackson patient insurance flow.

    Chains specialized agents:
    1. PatientFinderAgent - Finds patient element
    2. RPA actions - Opens patient (with modal handling)
    """

    def __init__(
        self,
        max_steps: int = 15,
        step_delay: float = 1.5,
    ):
        self.max_steps = max_steps
        self.step_delay = step_delay

        # Components
        self.omniparser = get_omniparser_client()
        self.capturer = get_screen_capturer()
        self.patient_finder = PatientFinderAgent()

        # RPA Bot instance for robust modal handling
        self.rpa = RPABotBase()

        # State
        self.execution_id = ""
        self.history: List[Dict[str, Any]] = []
        self.current_step = 0

    def run(self, patient_name: str) -> RunnerResult:
        """
        Run the flow to find and open patient detail.

        Args:
            patient_name: Name of patient to find

        Returns:
            RunnerResult with outcome
        """
        self.execution_id = str(uuid.uuid4())[:8]
        self.history = []
        self.current_step = 0
        patient_detail_opened = False  # Track if patient detail window is open

        logger.info("=" * 70)
        logger.info(" LOCAL JACKSON INSURANCE RUNNER - STARTING")
        logger.info(f" VERSION: {__version__}")
        logger.info("=" * 70)
        logger.info(f"[RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[RUNNER] Patient: {patient_name}")
        logger.info("=" * 70)

        try:
            # === PHASE 1: Find Patient (with retry for OCR failures) ===
            logger.info("[RUNNER] Phase 1: Finding patient...")
            max_retries = 3
            patient_result = None
            phase1_elements = None  # Store elements for Phase 2

            for attempt in range(1, max_retries + 1):
                patient_result, phase1_elements = self._phase1_find_patient(
                    patient_name
                )

                if patient_result.status == "found":
                    break
                elif patient_result.status == "retry":
                    logger.info(
                        f"[RUNNER] Retry {attempt}/{max_retries} - OCR didn't detect patient, retrying..."
                    )
                    self.rpa.stoppable_sleep(1.5)
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
                    patient_detail_open=False,  # Detail NOT open yet
                )

            patient_element_id = patient_result.element_id
            logger.info(
                f"[RUNNER] Phase 1 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 2: Open Patient (RPA) ===
            # CRITICAL: Pass Phase 1 elements to avoid new OmniParser call with different IDs
            logger.info("[RUNNER] Phase 2: Opening patient record...")
            self._phase2_open_patient(patient_element_id, phase1_elements)
            patient_detail_opened = True  # Mark that patient detail is now open
            logger.info("[RUNNER] Phase 2 complete - Patient detail open")

            logger.info("=" * 70)
            logger.info(" LOCAL JACKSON INSURANCE RUNNER - FINISHED")
            logger.info(f" Steps: {self.current_step}")
            logger.info("=" * 70)

            return RunnerResult(
                status=AgentStatus.FINISHED,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                history=self.history,
                patient_detail_open=True,
            )

        except Exception as e:
            logger.error(f"[RUNNER] Error: {e}", exc_info=True)
            return RunnerResult(
                status=AgentStatus.ERROR,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                error=str(e),
                history=self.history,
                patient_detail_open=patient_detail_opened,  # Use tracked state
            )

    def _phase1_find_patient(self, patient_name: str):
        """
        Phase 1: Use PatientFinderAgent to locate patient.

        Returns:
            Tuple of (agent_result, elements_list) - elements are reused in Phase 2
        """
        self.current_step += 1

        # Capture and parse screen (with ROI mask if configured)
        rois = get_agent_rois("jackson", "patient_finder")
        if rois:
            image_b64 = self.capturer.capture_with_mask_base64(rois)
            parsed = self.omniparser.parse_image(
                f"data:image/png;base64,{image_b64}", self.capturer.get_screen_size()
            )
            logger.info(f"[RUNNER] Phase 1 using ROI mask ({len(rois)} regions)")
        else:
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
        # Return both result AND elements for Phase 2 to reuse
        return result, elements

    def _phase2_open_patient(self, element_id: int, elements: list):
        """
        Phase 2: RPA to open patient.
        Uses robust modal handling for Same Name Alert and Assign Relationship modals.

        Args:
            element_id: ID of patient element from Phase 1
            elements: Elements list from Phase 1 (SAME IDs)
        """
        self.current_step += 1

        # CRITICAL: Use elements from Phase 1 - DO NOT re-capture!
        # OmniParser generates new IDs on each parse, causing wrong clicks

        # Double-click patient
        result = tools.click_element(element_id, elements, action="dblclick")
        self._record_step(
            "rpa",
            "dblclick_patient",
            f"Double-clicked patient element {element_id}: {result}",
        )

        # Wait for patient detail to load, handling modals that may appear
        logger.info("[RUNNER] Waiting for patient detail (with modal handling)...")
        self._handle_patient_open_modals()
        self.rpa.check_stop()
        
        # Wait for screen to fully stabilize
        logger.info("[RUNNER] Waiting 5s for screen to stabilize...")
        self.rpa.stoppable_sleep(5)

    def _handle_patient_open_modals(self):
        """
        Handle modals that may appear after double-clicking a patient:
        - Same Name Alert: Just click OK
        - Assign a Relationship: Click OK (first option is usually correct)
        - Info Modal: Press Enter
        """
        # Give time for potential modals to appear
        self.rpa.stoppable_sleep(3)

        # Check and handle modals in sequence (they may appear one after another)
        max_modal_checks = 3

        for _ in range(max_modal_checks):
            modal_handled = False

            # Check for Same Name Alert (just click OK)
            try:
                same_name_ok = config.get_rpa_setting(
                    "images.jackson_same_name_alert_ok"
                )
                location = pyautogui.locateOnScreen(same_name_ok, confidence=0.8)
                if location:
                    logger.info("[RUNNER] Same Name Alert detected - clicking OK")
                    self.rpa.safe_click(location, "Same Name Alert OK")
                    self._record_step(
                        "rpa", "handle_modal", "Same Name Alert - clicked OK"
                    )
                    self.rpa.stoppable_sleep(2)
                    modal_handled = True
                    continue
            except Exception:
                pass

            # Check for Assign Relationship (click OK to accept first/default option)
            try:
                assign_ok = config.get_rpa_setting(
                    "images.jackson_assign_relationship_ok"
                )
                location = pyautogui.locateOnScreen(assign_ok, confidence=0.8)
                if location:
                    logger.info(
                        "[RUNNER] Assign Relationship modal detected - clicking OK"
                    )
                    self.rpa.safe_click(location, "Assign Relationship OK")
                    self._record_step(
                        "rpa", "handle_modal", "Assign Relationship - clicked OK"
                    )
                    self.rpa.stoppable_sleep(2)
                    modal_handled = True
                    continue
            except Exception:
                pass

            # Check for Info Modal (press Enter)
            try:
                info_modal = config.get_rpa_setting("images.jackson_info_modal")
                location = pyautogui.locateOnScreen(info_modal, confidence=0.8)
                if location:
                    logger.info("[RUNNER] Info modal detected - pressing Enter")
                    pyautogui.press("enter")
                    self._record_step(
                        "rpa", "handle_modal", "Info Modal - pressed Enter"
                    )
                    self.rpa.stoppable_sleep(2)
                    modal_handled = True
                    continue
            except Exception:
                pass

            # If no modal was handled in this iteration, we're done
            if not modal_handled:
                break

        # Final wait after handling all modals
        self.rpa.stoppable_sleep(2)
        logger.info("[RUNNER] Modal handling complete")

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
