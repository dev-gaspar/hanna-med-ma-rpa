"""
PatientFinderAgent for Baptist EMR.
Finds a patient in the patient list across multiple hospital tabs.
Works iteratively like ReportFinderAgent - with actions, history, and loop detection.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are PatientFinderAgent for Baptist Health EMR (PowerChart).

TASK: Find the patient "{patient_name}" in the patient list visible on screen.

=== UNDERSTANDING BAPTIST PATIENT LIST ===

Baptist Health has 4 HOSPITAL TABS at the top of the patient list:
1. HH (Homestead Hospital) - Tab 1
2. SMH (South Miami Hospital) - Tab 2  
3. WKBH (West Kendall Baptist Hospital) - Tab 3
4. BHM (Baptist Hospital of Miami) - Tab 4

The patient could be in ANY of these tabs. You must search across ALL tabs.

=== YOUR ROLE ===

You are a FINDER, not an executor. Your job is to:
1. LOCATE the patient in the visible list
2. REPORT back the patient's element ID when found
3. NAVIGATE between hospital tabs to search

You DO NOT click on patients. You only REPORT when you find them.

=== AVAILABLE ACTIONS ===

| Status      | Action       | Effect                                                |
|-------------|--------------|-------------------------------------------------------|
| found       | -            | Patient located! Return their element ID. NO CLICK.   |
| running     | click_tab_1  | Switch to Hospital 1 (HH) using image recognition     |
| running     | click_tab_2  | Switch to Hospital 2 (SMH) using image recognition    |
| running     | click_tab_3  | Switch to Hospital 3 (WKBH) using image recognition   |
| running     | click_tab_4  | Switch to Hospital 4 (BHM) using image recognition    |
| running     | wait         | Wait for screen to load after clicking a tab          |
| not_found   | -            | All 4 tabs checked, patient not in any of them        |

IMPORTANT: Use click_tab_X actions to navigate between hospital tabs.
When you find the patient, just return status="found" + target_id. The system will handle the click.

=== HOW TO SEARCH ===

1. Scan the current patient list for "{patient_name}"
2. Patient names appear as "LASTNAME, FIRSTNAME" format (case-insensitive)
3. If patient IS visible → Return status="found" + target_id=<patient_element_id>
4. If patient NOT visible → Use click_tab_X to switch to another hospital tab
5. After clicking a tab, return action="wait" to let it load

=== OUTPUT RULES ===

- status="found" + target_id=<patient_element_id>
  → Patient is visible in the list. Return their ID. DO NOT CLICK.
  
- status="running" + action="click_tab_1" (or click_tab_2, click_tab_3, click_tab_4)
  → Patient not here. Switch to the specified hospital tab.
  → NO target_id needed - the tool uses image recognition.
  
- status="running" + action="wait"
  → Use this in TWO situations:
    1. Just clicked a tab, waiting for the new patient list to load
    2. OCR RETRY: You SEE the patient in the screenshot, but CANNOT find 
       a matching element ID in UI_ELEMENTS. Return "wait" to retry with fresh OCR.
  
- status="not_found"
  → All 4 hospital tabs have been checked, patient not found.

=== WHICH TAB AM I ON? ===

Look at the TABS ALREADY CHECKED section. If empty, you're on Tab 1 (HH).
Plan your search: check all 4 tabs systematically.

=== OCR RETRY STRATEGY ===

Sometimes OmniParser's OCR misses patient names. If you:
- See "{patient_name}" in the screenshot but can't find their ID in UI_ELEMENTS

Then return: status="running" + action="wait"

This will trigger a new screen capture with fresh OCR. 
You have up to 10 steps, so 1-2 retries are acceptable.

=== ROW-BASED FALLBACK (after 1-2 waits) ===

If OCR still fails after waiting, use ANY element in the SAME ROW:

FOR PATIENTS:
- If you SEE the patient but their name is NOT in UI_ELEMENTS
- Look for OTHER elements in that row: FIN number, physician name, icon, date
- Return status="found" + target_id=<any element in that row>
- Clicking any element in the row will select the patient!

EXAMPLE:
- You see "Partida, Jaime A" in row 3 but no name element exists
- UI_ELEMENTS has: [10] "945758058" (FIN), [11] "Blandon" (Physician)
- Return target_id=10 or target_id=11 → Row gets selected!

IMPORTANT: Do NOT wait more than 2 times. After 2 waits, use row-adjacent elements.

=== CRITICAL RULES ===

1. NEVER click on the patient row - only REPORT their ID
2. Use click_tab_X actions to switch tabs (no target_id needed)
3. target_id is ONLY needed when status="found"
4. After clicking a tab, the next step should be action="wait"
5. Check HISTORY and TABS ALREADY CHECKED to avoid revisiting tabs
6. Maximum 10 steps - be efficient!

=== IDENTIFYING PATIENT ROWS ===

Look for elements containing patient names in "LASTNAME, FIRSTNAME" format.
If exact name not found, look for adjacent elements (FIN, physician, etc.) in same row."""


USER_PROMPT = """Analyze this screenshot of the Baptist patient list.

=== CURRENT STATUS ===
Step: {current_step}/10
Patient to find: {patient_name}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== YOUR PREVIOUS ACTIONS ===
{history}

=== TABS ALREADY CHECKED ===
{checked_tabs}

=== DECISION TREE ===

1. Can you see "{patient_name}" in the patient list?
   → YES + Found ID in UI_ELEMENTS: Return status="found" + target_id=<patient_ID>
   → YES + Cannot find ID: Return status="running" + action="wait" (OCR retry)
   → NO: Go to step 2

2. Did you just click a hospital tab on the previous step?
   → YES: Return status="running" + action="wait"
          (Wait for the new patient list to load)
   → NO: Go to step 3

3. Are there hospital tabs you haven't searched yet?
   → YES: Return status="running" + action="click_tab_X" (where X is 1, 2, 3, or 4)
          Tab 1 = HH (Homestead Hospital)
          Tab 2 = SMH (South Miami Hospital)
          Tab 3 = WKBH (West Kendall Baptist Hospital)
          Tab 4 = BHM (Baptist Hospital of Miami)
   → NO: Return status="not_found"
          (All tabs checked, patient not found)

REMEMBER:
- "found" = patient visible AND you have their element ID (use target_id)
- "click_tab_X" = use image-based tool to switch tabs (NO target_id needed)
- "wait" = after clicking tab OR when you see patient but OCR missed the ID

Decide your response."""


# =============================================================================
# AGENT
# =============================================================================


class PatientFinderResult(BaseModel):
    """Structured output for PatientFinderAgent."""

    status: Literal["running", "found", "not_found", "error"] = Field(
        description="'found' when patient located, 'running' to click a tab and continue, 'not_found' if all tabs checked, 'error' if failed"
    )
    action: Optional[
        Literal["click_tab_1", "click_tab_2", "click_tab_3", "click_tab_4", "wait"]
    ] = Field(
        default=None,
        description="Action to perform. Only used when status='running'. 'click_tab_X' to switch to hospital tab X (1-4), 'wait' after clicking tab.",
    )
    target_id: Optional[int] = Field(
        default=None,
        description="Element ID. Only needed when status='found' - the patient row element ID.",
    )
    reasoning: str = Field(
        description="Explain: What you see → What you're trying → Why this action"
    )


class PatientFinderAgent(BaseAgent):
    """
    Agent that finds a specific patient in Baptist's patient list.
    Handles multiple hospital tabs - searches iteratively across all tabs.
    Works like ReportFinderAgent with actions, history, and loop detection.
    """

    emr_type = "baptist"
    agent_name = "patient_finder"
    max_steps = 10
    temperature = 0.2

    def get_output_schema(self) -> Type[BaseModel]:
        return PatientFinderResult

    def get_system_prompt(self, patient_name: str = "", **kwargs) -> str:
        return SYSTEM_PROMPT.format(patient_name=patient_name)

    def get_user_prompt(
        self,
        elements_text: str = "",
        patient_name: str = "",
        current_step: int = 1,
        history: str = "",
        checked_tabs: str = "None",
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            elements_text=elements_text,
            patient_name=patient_name,
            current_step=current_step,
            history=history,
            checked_tabs=checked_tabs,
        )

    def decide_action(
        self,
        patient_name: str,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
        current_step: int,
        checked_tabs: List[str] = None,
    ) -> PatientFinderResult:
        """
        Decide the next action to find the patient.

        Args:
            patient_name: Name of patient to find
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser
            history: List of previous action records
            current_step: Current step number (1-10)
            checked_tabs: List of hospital tab names already checked

        Returns:
            PatientFinderResult with action to take
        """
        checked_tabs = checked_tabs or []
        checked_tabs_str = (
            ", ".join(checked_tabs)
            if checked_tabs
            else "None (first tab is current view)"
        )

        logger.info(
            f"[PATIENT_FINDER] Step {current_step} - looking for '{patient_name}'..."
        )

        # Format elements before invoking
        elements_text = self.format_ui_elements(ui_elements)

        # Format history
        history_text = self._format_history(history)

        result = self.invoke(
            image_base64=image_base64,
            patient_name=patient_name,
            elements_text=elements_text,
            current_step=current_step,
            history=history_text,
            checked_tabs=checked_tabs_str,
        )

        logger.info(
            f"[PATIENT_FINDER] Decision: status={result.status}, action={result.action}, target_id={result.target_id}"
        )
        return result

    def _format_history(self, history: List[Dict[str, Any]]) -> str:
        """Format action history for the prompt."""
        if not history:
            return "No previous actions (this is step 1)."

        lines = []
        for h in history[-10:]:  # Last 10 actions
            step = h.get("step", "?")
            action = h.get("action", "?")
            reasoning = h.get("reasoning", "")[:500]  # Keep more reasoning for context
            lines.append(f"Step {step}: {action} - {reasoning}")

        return "\n".join(lines)
