"""
Steward Summary Runner - Local orchestrator for patient summary extraction.

Runner Phases (handled here):
- Phase 2 (Agent): PatientFinderAgent - Find patient in list with scroll support
- Phase 3 (RPA): Click patient and open Orders view
- Phase 4 (Agent): ReasonFinderAgent - Extract "Reason For Exam" from Orders
- Phase 5 (RPA): Navigate to Chart > Provider Notes (filter documents)
- Phase 6 (Agent): ReportFinderAgent - Find and select clinical document

Flow Phases (handled by StewardSummaryFlow):
- Phase 1 (RPA): Navigation to patient list
- Phase 7 (RPA): Capture document content (print preview, copy, close)
- Phase 8 (RPA): Cleanup and return to lobby

Note: This follows the same pattern as Jackson and Baptist runners.
The runner finds the report, the flow captures content and cleans up.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyautogui

from logger import logger
from config import config
from core.rpa_engine import RPABotBase
from agentic.emr.steward.patient_finder import PatientFinderAgent
from agentic.emr.steward.reason_finder import ReasonFinderAgent
from agentic.emr.steward.report_finder import ReportFinderAgent
from agentic.emr.steward import tools
from agentic.models import AgentStatus
from agentic.omniparser_client import get_omniparser_client
from agentic.screen_capturer import get_screen_capturer, get_agent_rois
from version import __version__


@dataclass
class RunnerResult:
    """Result from StewardSummaryRunner."""

    status: AgentStatus
    execution_id: str
    steps_taken: int = 0
    error: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    patient_detail_open: bool = False
    reason_for_exam: Optional[str] = None


class StewardSummaryRunner:
    """
    Local orchestrator for Steward patient summary flow (Meditech).

    Chains specialized agents:
    1. PatientFinderAgent - Finds patient in scrollable Rounds Patients list
    2. RPA actions - Opens patient chart
    3. ReasonFinderAgent - Extracts Reason For Exam from Orders
    4. ReportFinderAgent - Finds clinical document in Provider Notes
    """

    def __init__(
        self,
        max_steps: int = 30,
        step_delay: float = 1.5,
        vdi_enhance: bool = False,  # Disabled for Steward - not VDI
        doctor_specialty: str = None,
    ):
        self.max_steps = max_steps
        self.step_delay = step_delay
        self.vdi_enhance = vdi_enhance
        self.doctor_specialty = doctor_specialty

        # Components
        self.omniparser = get_omniparser_client()
        self.capturer = get_screen_capturer()
        self.patient_finder = PatientFinderAgent()
        self.reason_finder = ReasonFinderAgent(specialty=doctor_specialty or "")
        self.report_finder = ReportFinderAgent(doctor_specialty=doctor_specialty or "")

        # RPA Bot instance for robust handling
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
        patient_detail_opened = False

        logger.info("=" * 70)
        logger.info(" STEWARD RUNNER - STARTING")
        logger.info(f" VERSION: {__version__}")
        logger.info("=" * 70)
        logger.info(f"[RUNNER] Execution ID: {self.execution_id}")
        logger.info(f"[RUNNER] Patient: {patient_name}")
        logger.info(f"[RUNNER] Doctor Specialty: {self.doctor_specialty}")
        logger.info("=" * 70)

        try:
            # === PHASE 2: Find Patient (with scroll support) ===
            logger.info("[RUNNER] Phase 2: Finding patient in list...")
            patient_result, phase2_elements = self._phase2_find_patient_with_scroll(
                patient_name
            )

            if patient_result.status == "not_found" or patient_result.status == "error":
                logger.warning("[RUNNER] Patient not found in list")
                return RunnerResult(
                    status=AgentStatus.PATIENT_NOT_FOUND,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Patient '{patient_name}' not found in Rounds Patients list",
                    history=self.history,
                    patient_detail_open=False,
                )

            patient_element_id = patient_result.target_id
            logger.info(
                f"[RUNNER] Phase 2 complete - Patient at element {patient_element_id}"
            )

            # === PHASE 3: Click Patient + Click Orders (RPA) ===
            logger.info("[RUNNER] Phase 3: Clicking patient and opening Orders...")
            self._phase3_click_patient_and_orders(patient_element_id, phase2_elements)
            patient_detail_opened = True
            logger.info("[RUNNER] Phase 3 complete - Orders view open")

            # === PHASE 4: Find Reason For Consult (Agent) ===
            logger.info("[RUNNER] Phase 4: Finding Reason For Consult...")
            reason_result = self._phase4_find_reason_with_scroll()

            if reason_result.status == "not_found" or reason_result.status == "error":
                logger.warning(f"[RUNNER] Reason not found: {reason_result.reasoning}")
                return RunnerResult(
                    status=AgentStatus.ERROR,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error=f"Reason for {self.doctor_specialty} consult not found",
                    history=self.history,
                    patient_detail_open=True,
                    reason_for_exam=None,
                )

            reason_text = reason_result.reason_text
            logger.info(f"[RUNNER] Phase 4 complete - Reason: {reason_text}")

            # === PHASE 5: Navigate to Provider Notes (RPA) ===
            logger.info("[RUNNER] Phase 5: Navigating to Provider Notes...")
            self._phase5_navigate_to_provider_notes()
            logger.info("[RUNNER] Phase 5 complete - Document list visible")

            # === PHASE 6: Find Report (Agent) ===
            logger.info("[RUNNER] Phase 6: Finding clinical report...")
            report_found = self._phase6_find_report()

            if not report_found:
                logger.warning("[RUNNER] Report not found in Provider Notes")
                return RunnerResult(
                    status=AgentStatus.ERROR,
                    execution_id=self.execution_id,
                    steps_taken=self.current_step,
                    error="Clinical report not found in Provider Notes",
                    history=self.history,
                    patient_detail_open=True,
                    reason_for_exam=reason_text,
                )

            logger.info("[RUNNER] Phase 6 complete - Report found and selected")

            # === SUCCESS ===
            # Runner complete - Flow will handle content capture (Phase 7)
            logger.info("=" * 70)
            logger.info(" STEWARD RUNNER - SUCCESS")
            logger.info(f" Total steps: {self.current_step}")
            logger.info(f" Reason for exam: {reason_text[:50]}...")
            logger.info("=" * 70)

            return RunnerResult(
                status=AgentStatus.FINISHED,
                execution_id=self.execution_id,
                steps_taken=self.current_step,
                history=self.history,
                patient_detail_open=True,
                reason_for_exam=reason_text,
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

    def _phase2_find_patient_with_scroll(self, patient_name: str):
        """
        Phase 2: Use PatientFinderAgent iteratively to locate patient with scroll support.

        Steward's Meditech has a single scrollable patient list. The agent decides whether to:
        - Report the patient (when found)
        - Scroll down/up (to see more patients)
        - Wait (for screen to stabilize or OCR retry)

        Returns:
            Tuple of (agent_result, elements_list) or (result with not_found, elements)
        """
        MAX_PATIENT_STEPS = 15
        phase2_history: List[Dict[str, Any]] = []
        elements = []
        scroll_down_count = 0
        scroll_up_count = 0
        bottom_reached = False
        top_reached = False

        # Get ROIs for patient list region
        rois = get_agent_rois("steward", "patient_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(f"[RUNNER] Phase 2 using ROI mask ({len(rois)} regions)")
        else:
            logger.warning("[RUNNER] No ROI configured for steward patient_finder")

        for step in range(1, MAX_PATIENT_STEPS + 1):
            self.rpa.check_stop()
            self.current_step += 1

            # Build scroll state description
            scroll_state = self._build_scroll_state(
                scroll_down_count, scroll_up_count, bottom_reached, top_reached
            )

            logger.info(
                f"[RUNNER] Phase 2 Step {step}/{MAX_PATIENT_STEPS} - {scroll_state}"
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
                history=phase2_history,
                current_step=step,
                scroll_state=scroll_state,
            )

            # Record in both local phase2 history and global history
            phase2_history.append(
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
                logger.info(f"[RUNNER] Patient found! Element ID: {result.target_id}")

                class PatientFoundResult:
                    status = "found"
                    target_id = result.target_id

                return PatientFoundResult(), elements

            if result.status == "not_found":
                logger.warning("[RUNNER] Patient not found after searching entire list")

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

            # Handle running status - execute scroll actions
            if result.status == "running":
                if result.action == "scroll_down":
                    logger.info("[RUNNER] Scrolling DOWN in patient list...")
                    tools.scroll_down(clicks=2, roi_name="patient_list")
                    scroll_down_count += 1
                    self.rpa.stoppable_sleep(1.5)
                    continue

                elif result.action == "scroll_up":
                    logger.info("[RUNNER] Scrolling UP in patient list...")
                    tools.scroll_up(clicks=2, roi_name="patient_list")
                    scroll_up_count += 1
                    self.rpa.stoppable_sleep(1.5)
                    continue

                elif result.action == "wait":
                    logger.info("[RUNNER] Waiting for screen to stabilize...")
                    self.rpa.stoppable_sleep(2)
                    continue

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        # Exhausted max steps without finding patient
        logger.warning(
            f"[RUNNER] Phase 2 exhausted {MAX_PATIENT_STEPS} steps without finding patient"
        )

        class PatientNotFoundResult:
            status = "not_found"
            target_id = None

        return PatientNotFoundResult(), elements

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

    def _phase3_click_patient_and_orders(self, element_id: int, elements: list):
        """
        Phase 3: RPA to click patient and open Orders.
        Verifies orders_view is visible before continuing.

        Args:
            element_id: ID of patient element from Phase 2
            elements: Elements list from Phase 2
        """
        # Step 1: Click on patient name to select (single click, not double)
        self.current_step += 1
        result = tools.click_element(element_id, elements, action="click")
        self._record_step(
            "rpa",
            "click_patient",
            f"Clicked patient element {element_id}: {result}",
        )
        logger.info(f"[RUNNER] Clicked patient element {element_id}")
        self.rpa.stoppable_sleep(3)  # Wait for patient selection to register

        # Step 2: Click Orders button (using wait_for_element for robustness)
        self.current_step += 1
        orders_image = config.get_rpa_setting("images.steward_orders_btn")
        logger.info(f"[RUNNER] Looking for Orders button: {orders_image}")

        # Wait for Orders button to appear (patient may need time to load)
        location = self.rpa.wait_for_element(
            orders_image,
            timeout=10,
            confidence=0.7,
            description="Orders button",
        )
        if location:
            self.rpa.safe_click(location, "Orders Button")
            self._record_step("rpa", "click_orders", "Clicked Orders button")
            logger.info("[RUNNER] Orders button clicked")
        else:
            self._record_step("rpa", "click_orders", "Orders button not found")
            raise Exception("Orders button not found on screen after waiting")

        # Step 3: Wait for Orders view to load and verify it's visible
        self.current_step += 1
        orders_view_image = config.get_rpa_setting("images.steward_orders_view")
        logger.info(f"[RUNNER] Waiting for Orders view: {orders_view_image}")

        max_wait = 10  # Max seconds to wait
        for attempt in range(max_wait):
            try:
                location = pyautogui.locateOnScreen(orders_view_image, confidence=0.8)
                if location:
                    self._record_step(
                        "rpa", "verify_orders_view", "Orders view confirmed visible"
                    )
                    logger.info("[RUNNER] Orders view confirmed visible")
                    return
            except Exception:
                pass
            self.rpa.stoppable_sleep(1)
            logger.info(
                f"[RUNNER] Waiting for Orders view... ({attempt + 1}/{max_wait})"
            )

        # If we get here, orders_view was not found
        self._record_step(
            "rpa", "verify_orders_view", "Orders view not visible after waiting"
        )
        raise Exception("Orders view not visible after clicking Orders button")

    def _phase4_find_reason_with_scroll(self):
        """
        Phase 4: Use ReasonFinderAgent iteratively to locate Consult and extract reason.

        The agent decides whether to:
        - Scroll down/up to find Consult section
        - Click on Consult order to expand details
        - Extract reason from expanded details
        - Wait for UI to update

        Returns:
            ReasonFinderResult with reason_text or not_found status
        """
        MAX_REASON_STEPS = 15
        phase4_history: List[Dict[str, Any]] = []
        elements = []
        scroll_down_count = 0
        scroll_up_count = 0
        bottom_reached = False
        top_reached = False
        consult_clicked = False

        # Get ROIs for orders list region
        rois = get_agent_rois("steward", "reason_finder")

        for step in range(MAX_REASON_STEPS):
            self.current_step += 1
            logger.info(f"[RUNNER] Phase 4 Step {step + 1}/{MAX_REASON_STEPS}")

            # 1. Capture and parse screen with ROI mask (no VDI enhance needed for Steward)
            if rois:
                image_b64 = self.capturer.capture_with_mask_base64(rois)
                parsed = self.omniparser.parse_image(
                    f"data:image/png;base64,{image_b64}",
                    self.capturer.get_screen_size(),
                )
            else:
                parsed = self.omniparser.parse_screen()
                image_b64 = self._get_image_base64_from_parsed(parsed)

            elements = self._elements_to_dicts(parsed.elements) if parsed else []

            logger.info(f"[RUNNER] OmniParser found {len(elements)} elements")

            # 3. Build scroll state description
            scroll_state = self._build_scroll_state(
                scroll_down_count, scroll_up_count, bottom_reached, top_reached
            )
            if consult_clicked:
                scroll_state += " (Consult clicked, looking for reason)"

            # 4. Ask agent to decide action
            reason_result = self.reason_finder.decide_action(
                elements=elements,
                history=phase4_history,
                scroll_state=scroll_state,
                image_base64=image_b64,
            )

            # Record in history
            phase4_history.append(
                {
                    "step": step + 1,
                    "action": reason_result.action,
                    "status": reason_result.status,
                    "reasoning": reason_result.reasoning,
                    "target_id": reason_result.target_id,
                }
            )
            self._record_step(
                "reason_finder",
                reason_result.action or reason_result.status,
                reason_result.reasoning[:100],
            )

            # 5. Handle agent decision
            if reason_result.status == "found":
                logger.info(f"[RUNNER] Reason found: {reason_result.reason_text}")
                return reason_result

            if reason_result.status == "not_found":
                logger.warning("[RUNNER] Reason not found after full search")
                return reason_result

            if reason_result.status == "error":
                logger.error(f"[RUNNER] Agent error: {reason_result.reasoning}")
                return reason_result

            # Execute action
            if reason_result.action == "scroll_down":
                logger.info("[RUNNER] Scrolling DOWN in orders list...")
                tools.scroll_down(clicks=2, roi_name="orders_list")
                scroll_down_count += 1
                self.rpa.stoppable_sleep(1)

            elif reason_result.action == "scroll_up":
                logger.info("[RUNNER] Scrolling UP in orders list...")
                tools.scroll_up(clicks=2, roi_name="orders_list")
                scroll_up_count += 1
                self.rpa.stoppable_sleep(1)

            elif reason_result.action == "click":
                if reason_result.target_id is not None:
                    logger.info(f"[RUNNER] Clicking element {reason_result.target_id}")
                    tools.click_element(
                        reason_result.target_id, elements, action="click"
                    )
                    consult_clicked = True
                    self.rpa.stoppable_sleep(2)
                else:
                    logger.warning("[RUNNER] click without target_id")
                    self.rpa.stoppable_sleep(1)

            elif reason_result.action == "wait":
                logger.info("[RUNNER] Waiting for UI to update...")
                self.rpa.stoppable_sleep(2)
                continue

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        # Exhausted max steps without finding reason
        logger.warning(
            f"[RUNNER] Phase 4 exhausted {MAX_REASON_STEPS} steps without finding reason"
        )

        from agentic.emr.steward.reason_finder import ReasonFinderResult

        return ReasonFinderResult(
            status="not_found",
            action=None,
            target_id=None,
            reason_text=None,
            reasoning="Exhausted max steps without finding Consult/reason",
        )

    def _phase5_navigate_to_provider_notes(self):
        """
        Phase 5: RPA navigation from Orders view to Provider Notes document list.

        Steps:
        1. Click Chart tab
        2. Click Provider Notes
        3. Wait for Provider Notes to collapse/load
        4. Click Filter button
        5. Click Select All button
        6. Click General Filter button
        7. Click Apply Filter button
        8. Click first document to open it
        """
        # Step 1: Click Chart tab
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 1: Clicking Chart tab...")
        chart_image = config.get_rpa_setting("images.steward_chart")

        location = self.rpa.wait_for_element(
            chart_image,
            timeout=15,
            confidence=0.8,
            description="Chart tab",
        )
        if location:
            self.rpa.safe_click(location, "Chart tab")
            self._record_step("rpa", "click_chart", "Clicked Chart tab")
            logger.info("[RUNNER] Chart tab clicked")
        else:
            raise Exception("Chart tab not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        # Step 2: Click Provider Notes
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 2: Clicking Provider Notes...")
        provider_notes_image = config.get_rpa_setting("images.steward_provider_notes")

        location = self.rpa.wait_for_element(
            provider_notes_image,
            timeout=15,
            confidence=0.8,
            description="Provider Notes",
        )
        if location:
            self.rpa.safe_click(location, "Provider Notes")
            self._record_step("rpa", "click_provider_notes", "Clicked Provider Notes")
            logger.info("[RUNNER] Provider Notes clicked")
        else:
            raise Exception("Provider Notes not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        # Step 3: Click Provider Notes collapsed
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 3: Clicking Provider Notes collapsed...")
        collapsed_image = config.get_rpa_setting(
            "images.steward_provider_notes_collapsed"
        )

        location = self.rpa.wait_for_element(
            collapsed_image,
            timeout=15,
            confidence=0.8,
            description="Provider Notes collapsed",
        )
        if location:
            self.rpa.safe_click(location, "Provider Notes collapsed")
            self._record_step(
                "rpa",
                "click_provider_notes_collapsed",
                "Clicked Provider Notes collapsed",
            )
            logger.info("[RUNNER] Provider Notes collapsed clicked")
        else:
            raise Exception("Provider Notes collapsed not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        # Step 4: Click Filter button
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 4: Clicking Filter button...")
        filter_image = config.get_rpa_setting("images.steward_filter_btn")

        location = self.rpa.wait_for_element(
            filter_image,
            timeout=15,
            confidence=0.8,
            description="Filter button",
        )
        if location:
            self.rpa.safe_click(location, "Filter button")
            self._record_step("rpa", "click_filter", "Clicked Filter button")
            logger.info("[RUNNER] Filter button clicked")
        else:
            raise Exception("Filter button not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        # Step 5: Click Select All button
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 5: Clicking Select All button...")
        select_all_image = config.get_rpa_setting("images.steward_select_all_btn")

        location = self.rpa.wait_for_element(
            select_all_image,
            timeout=15,
            confidence=0.8,
            description="Select All button",
        )
        if location:
            self.rpa.safe_click(location, "Select All button")
            self._record_step("rpa", "click_select_all", "Clicked Select All button")
            logger.info("[RUNNER] Select All button clicked")
        else:
            raise Exception("Select All button not found on screen")

        self.rpa.stoppable_sleep(1)
        self.rpa.check_stop()

        # Step 6: Click General Filter button
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 6: Clicking General Filter button...")
        general_filter_image = config.get_rpa_setting(
            "images.steward_general_filter_btn"
        )

        location = self.rpa.wait_for_element(
            general_filter_image,
            timeout=15,
            confidence=0.8,
            description="General Filter button",
        )
        if location:
            self.rpa.safe_click(location, "General Filter button")
            self._record_step(
                "rpa", "click_general_filter", "Clicked General Filter button"
            )
            logger.info("[RUNNER] General Filter button clicked")
        else:
            raise Exception("General Filter button not found on screen")

        self.rpa.stoppable_sleep(1)
        self.rpa.check_stop()

        # Step 7: Click Apply Filter button
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 7: Clicking Apply Filter button...")
        apply_filter_image = config.get_rpa_setting("images.steward_apply_filter_btn")

        location = self.rpa.wait_for_element(
            apply_filter_image,
            timeout=15,
            confidence=0.8,
            description="Apply Filter button",
        )
        if location:
            self.rpa.safe_click(location, "Apply Filter button")
            self._record_step(
                "rpa", "click_apply_filter", "Clicked Apply Filter button"
            )
            logger.info("[RUNNER] Apply Filter button clicked")
        else:
            raise Exception("Apply Filter button not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        # Step 8: Click first document to open it
        self.current_step += 1
        logger.info("[RUNNER] Phase 5 Step 8: Clicking first document...")
        first_doc_image = config.get_rpa_setting("images.steward_first_document_btn")

        location = self.rpa.wait_for_element(
            first_doc_image,
            timeout=15,
            confidence=0.8,
            description="First document",
        )
        if location:
            self.rpa.safe_click(location, "First document")
            self._record_step("rpa", "click_first_document", "Clicked first document")
            logger.info("[RUNNER] First document clicked")
        else:
            raise Exception("First document not found on screen")

        self.rpa.stoppable_sleep(2)
        self.rpa.check_stop()

        logger.info("[RUNNER] Phase 5 navigation complete - Document list ready")

    def _phase6_find_report(self) -> bool:
        """
        Phase 6: Use ReportFinderAgent to find and select a clinical report.

        The agent analyzes the Provider Notes list and:
        - Scrolls through the document list
        - Clicks on documents to view content
        - Returns finished when valid clinical content is visible

        Returns:
            True if report found (status=finished), False otherwise
        """
        MAX_REPORT_STEPS = (
            60  # Increased from 50 for very long hospital stays (2+ months)
        )
        phase6_history: List[Dict[str, Any]] = []
        elements = []

        # Get ROIs for report finder (document_list + document_content)
        rois = get_agent_rois("steward", "report_finder")
        using_roi = len(rois) > 0
        if using_roi:
            logger.info(f"[RUNNER] Phase 6 using ROI mask ({len(rois)} regions)")
        else:
            logger.warning("[RUNNER] No ROI configured for steward report_finder")

        for step in range(1, MAX_REPORT_STEPS + 1):
            self.rpa.check_stop()
            self.current_step += 1

            logger.info(f"[RUNNER] Phase 6 Step {step}/{MAX_REPORT_STEPS}")

            # Capture and parse screen with ROI mask
            if using_roi:
                image_b64 = self.capturer.capture_with_mask_base64(rois)
                parsed = self.omniparser.parse_image(
                    f"data:image/png;base64,{image_b64}",
                    self.capturer.get_screen_size(),
                )
            else:
                parsed = self.omniparser.parse_screen()
                image_b64 = self._get_image_base64_from_parsed(parsed)

            elements = self._elements_to_dicts(parsed.elements) if parsed else []
            logger.info(f"[RUNNER] OmniParser found {len(elements)} elements")

            # Ask report finder agent to decide action
            report_result = self.report_finder.decide_action(
                image_base64=image_b64,
                ui_elements=elements,
                history=phase6_history,
                current_step=step,
            )

            # Record in history
            phase6_history.append(
                {
                    "step": step,
                    "action": report_result.action or report_result.status,
                    "status": report_result.status,
                    "reasoning": report_result.reasoning,
                    "target_id": report_result.target_id,
                }
            )
            self._record_step(
                "report_finder",
                report_result.action or report_result.status,
                report_result.reasoning[:100],
            )

            # Handle agent decision
            if report_result.status == "finished":
                logger.info("[RUNNER] Report found with valid clinical content!")
                return True

            if report_result.status == "error":
                logger.error(f"[RUNNER] Report finder error: {report_result.reasoning}")
                return False

            # Execute action
            if report_result.action == "scroll_down":
                logger.info("[RUNNER] Scrolling DOWN in document list...")
                tools.scroll_down(
                    clicks=4, roi_name="document_list"
                )  # 4 clicks for faster navigation
                self.rpa.stoppable_sleep(1.0)

            elif report_result.action == "scroll_up":
                logger.info("[RUNNER] Scrolling UP in document list...")
                tools.scroll_up(
                    clicks=4, roi_name="document_list"
                )  # 4 clicks for faster navigation
                self.rpa.stoppable_sleep(1.0)

            elif report_result.action == "click":
                if report_result.target_id is not None:
                    logger.info(
                        f"[RUNNER] Clicking document element {report_result.target_id}"
                    )
                    tools.click_element(
                        report_result.target_id, elements, action="click"
                    )
                    self.rpa.stoppable_sleep(2)
                else:
                    logger.warning("[RUNNER] click without target_id")
                    self.rpa.stoppable_sleep(1)

            elif report_result.action == "wait":
                logger.info("[RUNNER] Waiting for document content to load...")
                self.rpa.stoppable_sleep(2)
                continue

            # Delay before next step
            self.rpa.stoppable_sleep(self.step_delay)

        # Exhausted max steps without finding report
        logger.warning(
            f"[RUNNER] Phase 6 exhausted {MAX_REPORT_STEPS} steps without finding report"
        )
        return False

    def _record_step(self, agent: str, action: str, reasoning: str):
        """Record a step in the history."""
        self.history.append(
            {
                "step": self.current_step,
                "agent": agent,
                "action": action,
                "reasoning": reasoning,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def _elements_to_dicts(self, elements) -> List[Dict[str, Any]]:
        """Convert OmniParser elements to dictionaries."""
        return [
            {
                "id": el.id,
                "type": el.type,
                "content": el.content,
                "center": el.center,
                "bbox": el.bbox,
            }
            for el in elements
        ]

    def _get_image_base64_from_parsed(self, parsed) -> str:
        """Extract base64 image from parsed result."""
        if hasattr(parsed, "image_base64"):
            return parsed.image_base64
        return ""
