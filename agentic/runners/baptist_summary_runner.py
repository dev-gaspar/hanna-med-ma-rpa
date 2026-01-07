"""
Baptist Summary Runner - Local orchestrator for patient summary extraction.

Replaces the n8n-based AgentRunner with local agents:
1. PatientFinderAgent - Find patient in list (handles 4 hospital tabs)
2. RPA - Open patient, click Notes
3. ReportFinderAgent - Navigate tree to find report
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyautogui

from config import config
from core.rpa_engine import RPABotBase
from logger import logger

from agentic.emr.baptist.patient_finder import PatientFinderAgent
from agentic.emr.baptist.report_finder import ReportFinderAgent
from agentic.emr.baptist import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer, get_agent_rois
from version import __version__


@dataclass
class RunnerResult:
    """Result from BaptistSummaryRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    patient_detail_open: bool = (
        False  # True if patient detail window is open (for cleanup)
    )


class BaptistSummaryRunner:
    """
    Local orchestrator for Baptist patient summary flow.

    Chains specialized agents:
    1. PatientFinderAgent - Finds patient across 4 hospital tabs
    2. RPA actions - Opens patient and Notes (with modal handling)
    3. ReportFinderAgent - Navigates to report

    Key difference from Jackson: Baptist has 4 hospital tabs that need to be
    searched sequentially if patient not found in current tab.
    """

    # Maximum number of hospital tabs to check
    MAX_HOSPITAL_TABS = 4

    def __init__(
        self,
        max_steps: int = 30,
        step_delay: float = 1.5,
        vdi_enhance: bool = True,  # Enable VDI image enhancement by default for Baptist
    ):
        self.max_steps = max_steps
        self.step_delay = step_delay
        self.vdi_enhance = vdi_enhance  # Apply upscaling/contrast for VDI OCR

        # Components
        self.omniparser = get_omniparser_client()
        self.capturer = get_screen_capturer()
        self.patient_finder = PatientFinderAgent()
        self.report_finder = ReportFinderAgent()

        # RPA Bot instance for robust modal handling
        self.rpa = RPABotBase()

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
        patient_detail_opened = False  # Track if patient detail window is open

        logger.info("=" * 70)
        logger.info(" LOCAL BAPTIST RUNNER - STARTING")
        logger.info(f" VERSION: {__version__}")
        logger.info("=" * 70)
        logger.info(f"[RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[RUNNER] Patient: {patient_name}")
        logger.info("=" * 70)

        try:
            # === PHASE 1: Find Patient (across 4 hospital tabs) ===
            logger.info("[RUNNER] Phase 1: Finding patient...")
            patient_result, phase1_elements = self._phase1_find_patient_with_tabs(
                patient_name
            )

            if patient_result.status == "not_found" or patient_result.status == "error":
                logger.warning("[RUNNER] Patient not found in any hospital tab")
                return RunnerResult(
                    status=AgentStatus.PATIENT_NOT_FOUND,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Patient '{patient_name}' not found in any hospital tab",
                    history=self.history,
                    patient_detail_open=False,
                )

            patient_element_id = patient_result.target_id
            logger.info(
                f"[RUNNER] Phase 1 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 2: Open Patient + Notes (RPA) ===
            logger.info("[RUNNER] Phase 2: Opening patient record...")
            self._phase2_open_patient_and_notes(patient_element_id, phase1_elements)
            patient_detail_opened = True
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
                    patient_detail_open=True,
                )

            logger.info("=" * 70)
            logger.info(" LOCAL BAPTIST RUNNER - FINISHED")
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
                patient_detail_open=patient_detail_opened,
            )

    def _phase1_find_patient_with_tabs(self, patient_name: str):
        """
        Phase 1: Use PatientFinderAgent iteratively to locate patient across hospital tabs.

        Baptist Health has 4 hospital tabs. The agent decides whether to:
        - Click on the patient (when found)
        - Click on another hospital tab (to search there)
        - Wait (after clicking a tab, to let it load)

        Works like Phase 3 (ReportFinder) - iterative loop with history.

        Returns:
            Tuple of (agent_result, elements_list) or (result with not_found, elements)
        """
        MAX_PATIENT_STEPS = 10
        checked_tabs: List[str] = []
        phase1_history: List[Dict[str, Any]] = []
        elements = []
        patient_element_id = None

        # Get ROIs once for reuse
        rois = get_agent_rois("baptist", "patient_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(f"[RUNNER] Phase 1 using ROI mask ({len(rois)} regions)")

        for step in range(1, MAX_PATIENT_STEPS + 1):
            self.rpa.check_stop()
            self.current_step += 1

            logger.info(f"[RUNNER] Phase 1 Step {step}/{MAX_PATIENT_STEPS}")

            # Capture and parse screen (with optional VDI enhancement)
            if using_roi:
                if self.vdi_enhance:
                    # Apply enhancement: upscale 2x + contrast + sharpness
                    upscale_factor = 2.0
                    image_b64 = self.capturer.capture_with_mask_enhanced_base64(
                        rois,
                        enhance=True,
                        upscale_factor=upscale_factor,
                        contrast_factor=1.3,
                        sharpness_factor=1.5,
                    )
                    # Get original screen size for coordinate mapping
                    screen_size = self.capturer.get_screen_size()
                    # Calculate dynamic imgsz based on upscaled resolution
                    # Use max dimension of upscaled image, capped at 1920
                    upscaled_max = int(max(screen_size) * upscale_factor)
                    imgsz = min(upscaled_max, 1920)  # API max is 1920

                    parsed = self.omniparser.parse_image(
                        f"data:image/png;base64,{image_b64}",
                        screen_size,  # Original size for coordinate scaling
                        imgsz_override=imgsz,  # Dynamic imgsz for better detection
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
                # Patient found - agent returns the patient's element ID
                logger.info(f"[RUNNER] Patient found! Element ID: {result.target_id}")

                # Create a result-like object for compatibility
                class PatientFoundResult:
                    status = "found"
                    target_id = result.target_id

                return PatientFoundResult(), elements

            if result.status == "not_found":
                logger.warning("[RUNNER] Patient not found in any hospital tab")

                class PatientNotFoundResult:
                    status = "not_found"
                    target_id = None

                return PatientNotFoundResult(), elements

            if result.status == "error":
                logger.error(f"[RUNNER] Patient finder error: {result.reasoning}")

                class PatientErrorResult:
                    status = "error"
                    target_id = None

                return PatientErrorResult(), elements

            # Handle running status - execute the action
            if result.status == "running":
                if result.action == "click" and result.target_id is not None:
                    # Clicking on a hospital tab to search there
                    logger.info(
                        f"[RUNNER] Clicking hospital tab element {result.target_id}"
                    )
                    tools.click_element(result.target_id, elements, action="click")

                    # Extract tab name from reasoning for tracking
                    tab_name = f"Tab-{result.target_id}"
                    for tab_keyword in ["HH-", "smh", "wkbh", "BHM"]:
                        if tab_keyword.lower() in result.reasoning.lower():
                            tab_name = tab_keyword
                            break
                    checked_tabs.append(tab_name)

                    self.rpa.stoppable_sleep(2.5)  # Wait for tab to load
                    continue

                elif result.action == "wait":
                    logger.info("[RUNNER] Waiting for screen to load...")
                    self.rpa.stoppable_sleep(2)
                    continue

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        # Exhausted max steps without finding patient
        logger.warning(
            f"[RUNNER] Phase 1 exhausted {MAX_PATIENT_STEPS} steps without finding patient"
        )

        class PatientNotFoundResult:
            status = "not_found"
            target_id = None

        return PatientNotFoundResult(), elements

    def _phase2_open_patient_and_notes(self, element_id: int, elements: list):
        """
        Phase 2: RPA to open patient and click Notes.
        Uses robust modal handling for any alerts.

        Args:
            element_id: ID of patient element from Phase 1
            elements: Elements list from Phase 1 (SAME IDs)
        """
        self.current_step += 1

        # Double-click patient
        result = tools.click_element(element_id, elements, action="dblclick")
        self._record_step(
            "rpa",
            "dblclick_patient",
            f"Double-clicked patient element {element_id}: {result}",
        )

        # Wait for patient detail to load, handling any modals
        logger.info("[RUNNER] Waiting for patient detail (with modal handling)...")
        self._handle_patient_open_modals()
        self.rpa.check_stop()

        # Click Notes menu
        self.current_step += 1
        notes_found = self._click_notes_menu_with_modal_handling()

        if not notes_found:
            logger.warning("[RUNNER] Notes menu not found after handling modals")
            self._record_step("rpa", "click_notes", "Notes menu not found")
        else:
            logger.info("[RUNNER] First click on Notes menu registered")
            self._record_step(
                "rpa", "click_notes", "First click on Notes menu: success"
            )

            # Wait for screen to fully stabilize before confirmation click
            logger.info("[RUNNER] Waiting 5s for screen to stabilize...")
            self.rpa.stoppable_sleep(5)
            self.rpa.check_stop()

            # Confirmation click on Notes to ensure it's properly selected
            logger.info("[RUNNER] Confirmation click on Notes menu...")
            notes_image = config.get_rpa_setting("images.baptist_notes_menu")
            try:
                location = pyautogui.locateOnScreen(notes_image, confidence=0.8)
                if location:
                    self.rpa.safe_click(location, "Notes Menu (confirmation)")
                    logger.info("[RUNNER] Confirmation click on Notes: success")
                    self._record_step(
                        "rpa",
                        "click_notes_confirm",
                        "Confirmation click on Notes: success",
                    )
                else:
                    logger.info(
                        "[RUNNER] Notes already selected (not visible as button)"
                    )
                    self._record_step(
                        "rpa", "click_notes_confirm", "Notes already active"
                    )
            except Exception as e:
                logger.warning(f"[RUNNER] Confirmation click failed: {e}")
                self._record_step(
                    "rpa", "click_notes_confirm", f"Confirmation click failed: {e}"
                )

        # Wait for notes tree to fully load after confirmation
        logger.info("[RUNNER] Waiting 5s for notes tree to load...")
        self.rpa.stoppable_sleep(5)
        self.rpa.check_stop()

    def _handle_patient_open_modals(self):
        """
        Handle modals that may appear after double-clicking a patient.
        Baptist shows Assign Relationship modal that needs OK clicked.
        """
        # Give time for potential modals to appear
        self.rpa.stoppable_sleep(3)

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

            # If no modal was handled, we're done
            if not modal_handled:
                break

        # Final wait after handling modals
        self.rpa.stoppable_sleep(2)
        logger.info("[RUNNER] Modal handling complete")

    def _click_notes_menu_with_modal_handling(self) -> bool:
        """
        Click Notes menu using robust wait with modal handlers.
        Returns True if Notes menu was found and clicked.
        """
        # Baptist uses different image for notes menu
        notes_image = config.get_rpa_setting("images.baptist_notes_menu")
        if not notes_image:
            # Fallback to generic patient list tab if no specific notes menu
            notes_image = config.get_rpa_setting("images.baptist_report_document")

        if not notes_image:
            logger.warning("[RUNNER] No notes menu image configured for Baptist")
            return False

        # Define handler for Assign Relationship modal
        def handle_assign_relationship(loc):
            logger.info(
                "[RUNNER] Assign Relationship during Notes search - clicking OK"
            )
            self.rpa.safe_click(loc, "Assign Relationship OK")
            self.rpa.stoppable_sleep(2)

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
            target_image_path=notes_image,
            target_description="Notes Menu",
            handlers=handlers,
            timeout=30,
            confidence=0.8,
            auto_click=True,
        )

        return location is not None

    def _phase3_find_report(self) -> bool:
        """Phase 3: Use ReportFinderAgent in a loop until report found."""

        # Get ROIs for report finder
        rois = get_agent_rois("baptist", "report_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(f"[RUNNER] Phase 3 using ROI mask ({len(rois)} regions)")

        while self.current_step < self.max_steps:
            self.rpa.check_stop()
            self.current_step += 1

            logger.info(f"[RUNNER] Step {self.current_step}/{self.max_steps}")

            # Capture and parse (with optional VDI enhancement)
            if using_roi:
                if self.vdi_enhance:
                    # Apply enhancement: upscale 2x + contrast + sharpness
                    upscale_factor = 2.0
                    image_b64 = self.capturer.capture_with_mask_enhanced_base64(
                        rois,
                        enhance=True,
                        upscale_factor=upscale_factor,
                        contrast_factor=1.3,
                        sharpness_factor=1.5,
                    )
                    # Get original screen size for coordinate mapping
                    screen_size = self.capturer.get_screen_size()
                    # Calculate dynamic imgsz based on upscaled resolution
                    upscaled_max = int(max(screen_size) * upscale_factor)
                    imgsz = min(upscaled_max, 1920)  # API max is 1920

                    parsed = self.omniparser.parse_image(
                        f"data:image/png;base64,{image_b64}",
                        screen_size,  # Original size for coordinate scaling
                        imgsz_override=imgsz,  # Dynamic imgsz for better detection
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

            # Decide action
            result = self.report_finder.decide_action(
                image_base64=image_b64,
                ui_elements=elements,
                history=self.history,
                current_step=self.current_step,
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
            repeat = getattr(result, "repeat", 1) or 1
            self._execute_action(
                result.action, result.target_id, elements, repeat=repeat
            )

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        logger.warning("[RUNNER] Max steps reached without finding report")
        return False

    def _execute_action(
        self, action: str, target_id: Optional[int], elements: list, repeat: int = 1
    ):
        """Execute the action decided by the agent."""
        if action == "nav_up":
            tools.nav_up(times=repeat)
        elif action == "nav_down":
            tools.nav_down(times=repeat)
        elif action == "scroll_up":
            tools.scroll_tree_up(clicks=repeat)
        elif action == "scroll_down":
            tools.scroll_tree_down(clicks=repeat)
        elif action == "click" and target_id is not None:
            tools.click_element(target_id, elements, action="click")
        elif action == "dblclick" and target_id is not None:
            tools.click_element(target_id, elements, action="dblclick")
        elif action == "wait":
            logger.info("[RUNNER] Waiting...")
            self.rpa.stoppable_sleep(1)
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
