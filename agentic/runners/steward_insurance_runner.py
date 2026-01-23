"""
Steward Insurance Runner - Local orchestrator for patient insurance extraction.

Follows the same pattern as StewardSummaryRunner for batch compatibility:
1. PatientFinderAgent - Find patient in list (with scroll support)

The runner is designed to be called multiple times by a batch flow,
finding one patient at a time and returning their element ID.
Later phases (insurance extraction) will be added as RPA actions.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import config
from core.rpa_engine import RPABotBase
from core.vdi_input import stoppable_sleep
from logger import logger

from agentic.emr.steward.patient_finder import PatientFinderAgent
from agentic.emr.steward import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer, get_agent_rois
from version import __version__


@dataclass
class InsuranceRunnerResult:
    """Result from StewardInsuranceRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    patient_detail_open: bool = (
        False  # True if patient detail window is open (for cleanup)
    )
    patient_element_id: Optional[int] = None  # Element ID of found patient


class StewardInsuranceRunner:
    """
    Local orchestrator for Steward patient insurance flow.

    Chains:
    1. PatientFinderAgent - Finds patient in scrollable Rounds Patients list (returns element ID)

    Designed for batch compatibility:
    - Called once per patient by the batch flow
    - Returns result with patient_element_id for subsequent RPA actions
    - Does NOT handle EMR session - that's the flow's responsibility

    Key difference from StewardSummaryRunner:
    - Only Phase 1 (find patient) - no Report/Reason phases
    - Returns patient element ID for insurance-specific RPA actions
    """

    def __init__(
        self,
        max_steps: int = 15,
        step_delay: float = 1.5,
        vdi_enhance: bool = False,  # Disabled for Steward - not VDI
    ):
        self.max_steps = max_steps
        self.step_delay = step_delay
        self.vdi_enhance = vdi_enhance

        # Components
        self.omniparser = get_omniparser_client()
        self.capturer = get_screen_capturer()
        self.patient_finder = PatientFinderAgent()

        # RPA Bot instance for modal handling
        self.rpa = RPABotBase()

        # State
        self.execution_id = ""
        self.history: List[Dict[str, Any]] = []
        self.current_step = 0

    def run(self, patient_name: str) -> InsuranceRunnerResult:
        """
        Run the flow to find patient.

        Args:
            patient_name: Name of patient to find

        Returns:
            InsuranceRunnerResult with outcome including patient_element_id
        """
        self.execution_id = str(uuid.uuid4())[:8]
        self.history = []
        self.current_step = 0

        logger.info("=" * 70)
        logger.info(" STEWARD INSURANCE RUNNER - STARTING")
        logger.info(f" VERSION: {__version__}")
        logger.info("=" * 70)
        logger.info(f"[INSURANCE-RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[INSURANCE-RUNNER] Patient: {patient_name}")
        logger.info("=" * 70)

        try:
            # === PHASE 1: Find Patient (with scroll support) ===
            logger.info("[INSURANCE-RUNNER] Phase 1: Finding patient...")
            patient_result, phase1_elements = self._phase1_find_patient_with_scroll(
                patient_name
            )

            if patient_result.status == "not_found" or patient_result.status == "error":
                logger.warning(
                    "[INSURANCE-RUNNER] Patient not found in Rounds Patients list"
                )
                return InsuranceRunnerResult(
                    status=AgentStatus.PATIENT_NOT_FOUND,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Patient '{patient_name}' not found in Rounds Patients list",
                    history=self.history,
                    patient_detail_open=False,
                    patient_element_id=None,
                )

            patient_element_id = patient_result.target_id
            logger.info(
                f"[INSURANCE-RUNNER] Phase 1 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 2: Click Patient (RPA) ===
            logger.info("[INSURANCE-RUNNER] Phase 2: Clicking on patient...")
            self._phase2_click_patient(patient_element_id, phase1_elements)
            logger.info("[INSURANCE-RUNNER] Phase 2 complete - Patient clicked")

            logger.info("=" * 70)
            logger.info(" STEWARD INSURANCE RUNNER - FINISHED")
            logger.info(f" Steps: {self.current_step}")
            logger.info(f" Patient Element ID: {patient_element_id}")
            logger.info("=" * 70)

            return InsuranceRunnerResult(
                status=AgentStatus.FINISHED,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                history=self.history,
                patient_detail_open=True,  # Patient detail is now open
                patient_element_id=patient_element_id,
            )

        except Exception as e:
            logger.error(f"[INSURANCE-RUNNER] Error: {e}", exc_info=True)
            return InsuranceRunnerResult(
                status=AgentStatus.ERROR,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                error=str(e),
                history=self.history,
                patient_detail_open=False,
                patient_element_id=None,
            )

    def _phase1_find_patient_with_scroll(self, patient_name: str):
        """
        Phase 1: Use PatientFinderAgent iteratively to locate patient with scroll support.

        Steward's Meditech has a single scrollable patient list. The agent decides whether to:
        - Report the patient (when found)
        - Scroll down/up (to see more patients)
        - Wait (for screen to stabilize or OCR retry)

        Returns:
            Tuple of (agent_result, elements_list) or (result with not_found, elements)
        """
        MAX_PATIENT_STEPS = 15
        phase1_history: List[Dict[str, Any]] = []
        elements = []
        scroll_down_count = 0
        scroll_up_count = 0
        bottom_reached = False
        top_reached = False

        # Get ROIs for patient list region
        rois = get_agent_rois("steward", "patient_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(
                f"[INSURANCE-RUNNER] Phase 1 using ROI mask ({len(rois)} regions)"
            )
        else:
            logger.warning(
                "[INSURANCE-RUNNER] No ROI configured for steward patient_finder"
            )

        for step in range(1, MAX_PATIENT_STEPS + 1):
            self.rpa.check_stop()
            self.current_step += 1

            # Build scroll state description
            scroll_state = self._build_scroll_state(
                scroll_down_count, scroll_up_count, bottom_reached, top_reached
            )

            logger.info(
                f"[INSURANCE-RUNNER] Phase 1 Step {step}/{MAX_PATIENT_STEPS} - {scroll_state}"
            )

            # Capture and parse screen with ROI mask (no VDI enhance needed for Steward)
            if using_roi:
                image_b64 = self.capturer.capture_with_mask_base64(rois)
                parsed = self.omniparser.parse_image(
                    f"data:image/png;base64,{image_b64}",
                    self.capturer.get_screen_size(),
                )
            else:
                parsed = self.omniparser.parse_screen()
                image_b64 = self._get_image_base64_from_parsed(parsed)

            elements = self._elements_to_dicts(parsed.elements)

            # Run agent with history and scroll context
            result = self.patient_finder.decide_action(
                patient_name=patient_name,
                image_base64=image_b64,
                ui_elements=elements,
                history=phase1_history,
                current_step=step,
                scroll_state=scroll_state,
            )

            # Record in both local phase1 history and global history
            phase1_history.append(
                {
                    "step": step,
                    "action": result.action or result.status,
                    "reasoning": result.reasoning,
                }
            )
            self._record_step(
                "patient_finder", result.action or result.status, result.reasoning
            )

            # Handle terminal statuses
            if result.status == "found":
                logger.info(
                    f"[INSURANCE-RUNNER] Patient found! Element ID: {result.target_id}"
                )

                class PatientFoundResult:
                    status = "found"
                    target_id = result.target_id

                return PatientFoundResult(), elements

            if result.status == "not_found":
                logger.warning(
                    "[INSURANCE-RUNNER] Patient not found after searching entire list"
                )

                class PatientNotFoundResult:
                    status = "not_found"
                    target_id = None

                return PatientNotFoundResult(), elements

            if result.status == "error":
                logger.error(
                    f"[INSURANCE-RUNNER] Patient finder error: {result.reasoning}"
                )

                class PatientErrorResult:
                    status = "error"
                    target_id = None

                return PatientErrorResult(), elements

            # Handle running status - execute scroll actions
            if result.status == "running":
                if result.action == "scroll_down":
                    logger.info("[INSURANCE-RUNNER] Scrolling DOWN in patient list...")
                    tools.scroll_down(clicks=2, roi_name="patient_list")
                    scroll_down_count += 1
                    self.rpa.stoppable_sleep(1.5)
                    continue

                elif result.action == "scroll_up":
                    logger.info("[INSURANCE-RUNNER] Scrolling UP in patient list...")
                    tools.scroll_up(clicks=2, roi_name="patient_list")
                    scroll_up_count += 1
                    self.rpa.stoppable_sleep(1.5)
                    continue

                elif result.action == "wait":
                    logger.info("[INSURANCE-RUNNER] Waiting for screen to stabilize...")
                    self.rpa.stoppable_sleep(2)
                    continue

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        # Exhausted max steps without finding patient
        logger.warning(
            f"[INSURANCE-RUNNER] Phase 1 exhausted {MAX_PATIENT_STEPS} steps without finding patient"
        )

        class PatientNotFoundResult:
            status = "not_found"
            target_id = None

        return PatientNotFoundResult(), elements

    def _phase2_click_patient(self, element_id: int, elements: list):
        """
        Phase 2: RPA to click on found patient.

        Args:
            element_id: ID of patient element from Phase 1
            elements: Elements list from Phase 1 (SAME IDs)
        """
        self.current_step += 1

        # Click patient to select
        result = tools.click_element(element_id, elements, action="click")
        self._record_step(
            "rpa",
            "click_patient",
            f"Clicked patient element {element_id}: {result}",
        )
        logger.info(f"[INSURANCE-RUNNER] Clicked patient element {element_id}")

        # Wait for patient detail to load
        self.rpa.stoppable_sleep(3)

    def _build_scroll_state(
        self,
        scroll_down_count: int,
        scroll_up_count: int,
        bottom_reached: bool,
        top_reached: bool,
    ) -> str:
        """Build a descriptive scroll state string for the agent."""
        if scroll_down_count == 0 and scroll_up_count == 0:
            return "Not scrolled yet (at initial view)"

        parts = []
        if scroll_down_count > 0:
            parts.append(f"Scrolled DOWN {scroll_down_count} times")
        if scroll_up_count > 0:
            parts.append(f"Scrolled UP {scroll_up_count} times")
        if bottom_reached:
            parts.append("(bottom of list reached)")
        if top_reached:
            parts.append("(top of list reached)")

        return ", ".join(parts) if parts else "Unknown state"

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
        """Extract base64 image from parsed screen."""
        if parsed.labeled_image_url and parsed.labeled_image_url.startswith("data:"):
            parts = parsed.labeled_image_url.split(",", 1)
            if len(parts) == 2:
                return parts[1]
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
