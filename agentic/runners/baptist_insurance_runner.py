"""
Baptist Insurance Runner - Local orchestrator for patient insurance extraction.

Follows the same pattern as BaptistSummaryRunner for batch compatibility:
1. PatientFinderAgent - Find patient in list (handles 4 hospital tabs)
2. RPA - Double-click patient, click Provider Face Sheet

The runner is designed to be called multiple times by a batch flow,
finding one patient at a time and opening their Face Sheet.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyautogui

from config import config
from core.rpa_engine import RPABotBase
from core.vdi_input import stoppable_sleep
from logger import logger

from agentic.emr.baptist.patient_finder import PatientFinderAgent
from agentic.emr.baptist import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer, get_agent_rois
from version import __version__


@dataclass
class InsuranceRunnerResult:
    """Result from BaptistInsuranceRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    patient_detail_open: bool = (
        False  # True if patient detail window is open (for cleanup)
    )


class BaptistInsuranceRunner:
    """
    Local orchestrator for Baptist patient insurance flow.

    Chains:
    1. PatientFinderAgent - Finds patient across 4 hospital tabs (returns element ID)
    2. RPA - Double-click patient, click Provider Face Sheet

    Designed for batch compatibility:
    - Called once per patient by the batch flow
    - Returns result with patient_detail_open flag for batch cleanup
    - Does NOT handle EMR session - that's the flow's responsibility

    Key difference from BaptistSummaryRunner:
    - Clicks Face Sheet instead of Notes
    - No ReportFinder phase (insurance is on Face Sheet directly)
    """

    MAX_HOSPITAL_TABS = 4

    def __init__(
        self,
        max_steps: int = 15,
        step_delay: float = 1.5,
        vdi_enhance: bool = True,  # Enable VDI image enhancement by default
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
        Run the flow to find patient and open Face Sheet.

        Args:
            patient_name: Name of patient to find

        Returns:
            InsuranceRunnerResult with outcome
        """
        self.execution_id = str(uuid.uuid4())[:8]
        self.history = []
        self.current_step = 0
        patient_detail_opened = False

        logger.info("=" * 70)
        logger.info(" BAPTIST INSURANCE RUNNER - STARTING")
        logger.info(f" VERSION: {__version__}")
        logger.info("=" * 70)
        logger.info(f"[INSURANCE-RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[INSURANCE-RUNNER] Patient: {patient_name}")
        logger.info("=" * 70)

        try:
            # === PHASE 1: Find Patient (across 4 hospital tabs) ===
            logger.info("[INSURANCE-RUNNER] Phase 1: Finding patient...")
            patient_result, phase1_elements = self._phase1_find_patient_with_tabs(
                patient_name
            )

            if patient_result.status == "not_found" or patient_result.status == "error":
                logger.warning(
                    "[INSURANCE-RUNNER] Patient not found in any hospital tab"
                )
                return InsuranceRunnerResult(
                    status=AgentStatus.PATIENT_NOT_FOUND,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Patient '{patient_name}' not found in any hospital tab",
                    history=self.history,
                    patient_detail_open=False,
                )

            patient_element_id = patient_result.target_id
            logger.info(
                f"[INSURANCE-RUNNER] Phase 1 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 2: Open Patient + Face Sheet (RPA) ===
            logger.info("[INSURANCE-RUNNER] Phase 2: Opening patient and Face Sheet...")
            self._phase2_open_patient_and_face_sheet(
                patient_element_id, phase1_elements
            )
            patient_detail_opened = True
            logger.info("[INSURANCE-RUNNER] Phase 2 complete - Face Sheet open")

            logger.info("=" * 70)
            logger.info(" BAPTIST INSURANCE RUNNER - FINISHED")
            logger.info(f" Steps: {self.current_step}")
            logger.info("=" * 70)

            return InsuranceRunnerResult(
                status=AgentStatus.FINISHED,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                history=self.history,
                patient_detail_open=True,
            )

        except Exception as e:
            logger.error(f"[INSURANCE-RUNNER] Error: {e}", exc_info=True)
            return InsuranceRunnerResult(
                status=AgentStatus.ERROR,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                error=str(e),
                history=self.history,
                patient_detail_open=patient_detail_opened,
            )

    def _phase1_find_patient_with_tabs(self, patient_name: str):
        """
        Phase 1: Use PatientFinderAgent to locate patient across hospital tabs.

        Baptist Health has 4 hospital tabs. The agent decides whether to:
        - Return patient element ID (when found)
        - Click on another hospital tab (to search there)
        - Wait (after clicking a tab, to let it load)

        PatientFinder only RETURNS the element ID - it does NOT click.

        Returns:
            Tuple of (result_with_element_id, elements_list)
        """
        MAX_PATIENT_STEPS = 10
        checked_tabs: List[str] = []
        phase1_history: List[Dict[str, Any]] = []
        elements = []

        # Get ROIs once for reuse
        rois = get_agent_rois("baptist", "patient_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(
                f"[INSURANCE-RUNNER] Phase 1 using ROI mask ({len(rois)} regions)"
            )

        for step in range(1, MAX_PATIENT_STEPS + 1):
            self.rpa.check_stop()
            self.current_step += 1

            logger.info(f"[INSURANCE-RUNNER] Phase 1 Step {step}/{MAX_PATIENT_STEPS}")

            # Capture and parse screen (with VDI enhancement)
            if using_roi:
                if self.vdi_enhance:
                    upscale_factor = 2.0
                    image_b64 = self.capturer.capture_with_mask_enhanced_base64(
                        rois,
                        enhance=True,
                        upscale_factor=upscale_factor,
                        contrast_factor=1.3,
                        sharpness_factor=1.5,
                    )
                    screen_size = self.capturer.get_screen_size()
                    upscaled_max = int(max(screen_size) * upscale_factor)
                    imgsz = min(upscaled_max, 1920)

                    parsed = self.omniparser.parse_image(
                        f"data:image/png;base64,{image_b64}",
                        screen_size,
                        imgsz_override=imgsz,
                    )
                else:
                    image_b64 = self.capturer.capture_with_mask_base64(rois)
                    parsed = self.omniparser.parse_image(
                        f"data:image/png;base64,{image_b64}",
                        self.capturer.get_screen_size(),
                    )
            else:
                parsed = self.omniparser.parse_screen()
                image_b64 = self._get_image_base64_from_parsed(parsed)

            elements = self._elements_to_dicts(parsed.elements)

            # Run agent with history and checked_tabs context
            result = self.patient_finder.decide_action(
                patient_name=patient_name,
                image_base64=image_b64,
                ui_elements=elements,
                history=phase1_history,
                current_step=step,
                checked_tabs=checked_tabs,
            )

            # Record step
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
                # Patient found - return element ID (NO clicking here)
                logger.info(
                    f"[INSURANCE-RUNNER] Patient found! Element ID: {result.target_id}"
                )

                class PatientFoundResult:
                    status = "found"
                    target_id = result.target_id

                return PatientFoundResult(), elements

            if result.status == "not_found":
                logger.warning(
                    "[INSURANCE-RUNNER] Patient not found in any hospital tab"
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

            # Handle running status - execute tab navigation
            if result.status == "running":
                if result.action == "click_tab_1":
                    logger.info("[INSURANCE-RUNNER] Clicking Hospital Tab 1 (HH)")
                    tools.click_tab_hospital_1()
                    checked_tabs.append("HH")
                    stoppable_sleep(2.5)
                    continue

                elif result.action == "click_tab_2":
                    logger.info("[INSURANCE-RUNNER] Clicking Hospital Tab 2 (SMH)")
                    tools.click_tab_hospital_2()
                    checked_tabs.append("SMH")
                    stoppable_sleep(2.5)
                    continue

                elif result.action == "click_tab_3":
                    logger.info("[INSURANCE-RUNNER] Clicking Hospital Tab 3 (WKBH)")
                    tools.click_tab_hospital_3()
                    checked_tabs.append("WKBH")
                    stoppable_sleep(2.5)
                    continue

                elif result.action == "click_tab_4":
                    logger.info("[INSURANCE-RUNNER] Clicking Hospital Tab 4 (BHM)")
                    tools.click_tab_hospital_4()
                    checked_tabs.append("BHM")
                    stoppable_sleep(2.5)
                    continue

                elif result.action == "wait":
                    logger.info("[INSURANCE-RUNNER] Waiting for screen to load...")
                    stoppable_sleep(2)
                    continue

            stoppable_sleep(self.step_delay)

        # Exhausted max steps
        logger.warning(
            f"[INSURANCE-RUNNER] Phase 1 exhausted {MAX_PATIENT_STEPS} steps"
        )

        class PatientNotFoundResult:
            status = "not_found"
            target_id = None

        return PatientNotFoundResult(), elements

    def _phase2_open_patient_and_face_sheet(self, element_id: int, elements: list):
        """
        Phase 2: RPA to open patient and click Provider Face Sheet.
        Uses robust modal handling for any alerts.

        Args:
            element_id: ID of patient element from Phase 1
            elements: Elements list from Phase 1 (SAME IDs)
        """
        self.current_step += 1

        # Double-click patient to open detail
        result = tools.click_element(element_id, elements, action="dblclick")
        self._record_step(
            "rpa",
            "dblclick_patient",
            f"Double-clicked patient element {element_id}: {result}",
        )

        # Wait for patient detail to load, handling modals
        logger.info(
            "[INSURANCE-RUNNER] Waiting for patient detail (with modal handling)..."
        )
        self._handle_patient_open_modals()
        self.rpa.check_stop()

        # Click Provider Face Sheet button
        self.current_step += 1
        face_sheet_found = self._click_face_sheet_with_modal_handling()

        if not face_sheet_found:
            raise Exception("Provider Face Sheet button not found")

        logger.info("[INSURANCE-RUNNER] Provider Face Sheet clicked successfully")
        self._record_step("rpa", "click_face_sheet", "Provider Face Sheet: success")

        # Wait for Face Sheet to load
        logger.info("[INSURANCE-RUNNER] Waiting for Face Sheet to load...")
        stoppable_sleep(3)

    def _handle_patient_open_modals(self):
        """
        Handle modals that may appear after double-clicking patient.
        Baptist shows Assign Relationship modal that needs OK clicked.
        """
        stoppable_sleep(3)

        max_modal_checks = 3
        for _ in range(max_modal_checks):
            modal_handled = False

            # Check for Assign Relationship OK button
            try:
                assign_ok = config.get_rpa_setting(
                    "images.baptist_assign_relationship_ok"
                )
                location = pyautogui.locateOnScreen(assign_ok, confidence=0.8)
                if location:
                    logger.info(
                        "[INSURANCE-RUNNER] Assign Relationship modal - clicking OK"
                    )
                    self.rpa.safe_click(location, "Assign Relationship OK")
                    self._record_step(
                        "rpa", "handle_modal", "Assign Relationship - clicked OK"
                    )
                    stoppable_sleep(2)
                    modal_handled = True
                    continue
            except Exception:
                pass

            if not modal_handled:
                break

        stoppable_sleep(2)
        logger.info("[INSURANCE-RUNNER] Modal handling complete")

    def _click_face_sheet_with_modal_handling(self) -> bool:
        """
        Click Provider Face Sheet button using robust wait.
        Returns True if found and clicked.
        """
        face_sheet_image = config.get_rpa_setting("images.baptist_provider_face_sheet")
        if not face_sheet_image:
            logger.warning("[INSURANCE-RUNNER] No Face Sheet image configured")
            return False

        # Define handler for Assign Relationship modal
        def handle_assign_relationship(loc):
            logger.info(
                "[INSURANCE-RUNNER] Assign Relationship during Face Sheet search - clicking OK"
            )
            self.rpa.safe_click(loc, "Assign Relationship OK")
            stoppable_sleep(2)

        handlers = {}
        try:
            assign_ok = config.get_rpa_setting("images.baptist_assign_relationship_ok")
            if assign_ok:
                handlers[assign_ok] = (
                    "Assign Relationship",
                    handle_assign_relationship,
                )
        except Exception:
            pass

        # Use robust wait with modal handlers
        location = self.rpa.robust_wait_for_element(
            target_image_path=face_sheet_image,
            target_description="Provider Face Sheet",
            handlers=handlers,
            timeout=30,
            confidence=0.8,
            auto_click=True,
        )

        return location is not None

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
