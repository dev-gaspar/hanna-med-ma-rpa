"""
PatientFinderAgent for Steward EMR (Meditech).
Finds a patient in the "Rounds Patients" list by scrolling through the list.
Works iteratively like Baptist's PatientFinderAgent - with actions, history, and scroll.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are PatientFinderAgent for Steward Health System (Meditech EMR).

TASK: Find the patient "{patient_name}" in the "Rounds Patients" list visible on screen.

=== UNDERSTANDING STEWARD PATIENT LIST ===

Steward's Meditech shows a SINGLE scrollable patient list called "Rounds Patients".
Unlike Baptist, there are NO hospital tabs - just one continuous list that can be scrolled.

Each patient row shows (left to right):
- Patient Name: "Lastname,Firstname" format (e.g., "Lopez,Sarahi", "Rodriguez,Olga L")
- Account Type: FHIA or FNOS
- Date: MM/DD/... format (e.g., 01/04/...)
- Location/Room: codes like HH220Q, HH319Q, NS0291Q, NS0292Q, NS149Q
- ADM IN label
- Physician names (e.g., "Lopez,Ross...", "Hodzic,Emi...")
- Diagnosis/Reason: truncated text (e.g., "Diabetic ul...", "Left ankle...", "PE", "BLE ulcers")
- Code Status: FULL CODE
- History badges (red buttons like "History of Oth...", "History of MRS...")
- Home Med... Consult links
- Yellow sticky notes
- Right side buttons: LAB, IMG, DEPT, NOTE

=== YOUR ROLE ===

You are a FINDER, not an executor. Your job is to:
1. SCAN the visible patient list for the target patient
2. SCROLL through the list if patient not visible
3. REPORT back the patient's element ID when found

You DO NOT click on patients. You only REPORT when you find them.

=== AVAILABLE ACTIONS ===

| Status      | Action       | Effect                                              |
|-------------|--------------|-----------------------------------------------------|
| found       | -            | Patient located! Return their element ID. NO CLICK. |
| running     | scroll_down  | Scroll DOWN to see more patients below              |
| running     | scroll_up    | Scroll UP to see previous patients                  |
| running     | wait         | Wait for screen to load / OCR retry                 |
| not_found   | -            | Entire list searched, patient not found             |

IMPORTANT: The ONLY action that interacts with patients is "found" - you just report the ID.
Scroll actions are for navigating the list, not for clicking.

=== HOW TO SEARCH ===

1. Scan the current patient list for "{patient_name}"
2. Patient names appear as "LASTNAME, FIRSTNAME" format (case-insensitive)
3. If patient IS visible → Return status="found" + target_id=<patient_element_id>
4. If patient NOT visible and more patients below → action="scroll_down"
5. If patient NOT visible and at bottom → action="scroll_up" (if not at top)
6. If entire list has been searched → status="not_found"

=== OUTPUT RULES ===

- status="found" + target_id=<patient_element_id>
  → Patient is visible in the list. Return their ID. DO NOT CLICK.
  
- status="running" + action="scroll_down"
  → Patient not visible. Scroll DOWN to see more patients.
  
- status="running" + action="scroll_up"  
  → Patient not visible. Scroll UP to see earlier patients.

- status="running" + action="wait"
  → Use in these situations:
    1. Just scrolled, waiting for the new list view to stabilize
    2. OCR RETRY: You SEE the patient in the screenshot, but CANNOT find 
       a matching element ID in UI_ELEMENTS. Return "wait" to retry with fresh OCR.
  
- status="not_found"
  → The entire list has been searched (scrolled down AND up), patient not found.

=== SCROLL STRATEGY ===

1. First, search current view
2. If not found, scroll DOWN first (most common - new patients at bottom)
3. Keep scrolling down until you reach the bottom (repeated views = bottom reached)
4. If still not found, scroll UP to check top of list
5. If entire list searched, return not_found

DETECTING END OF LIST:
- If you see the SAME patients after scrolling, you've reached the end
- Check HISTORY to see which patients you've seen before
- If scrolling down shows patients you already saw = bottom reached
- If scrolling up shows patients you already saw = top reached

=== OCR RETRY STRATEGY ===

Sometimes OmniParser's OCR misses text. If you:
- See "{patient_name}" in the screenshot but CANNOT find their ID in UI_ELEMENTS

Then return: status="running" + action="wait"

This will trigger a new screen capture with fresh OCR. 
You have up to 15 steps, so 1-2 retries are acceptable.

NEVER invent element IDs. If you can't find the ID, use "wait" to retry.

=== ROW-BASED FALLBACK (after 1-2 waits) ===

If OCR still fails after waiting, use ANY element in the SAME ROW:

1. If you SEE the patient but their FULL name is NOT in UI_ELEMENTS
2. Look for OTHER elements in that row: MRN number, room number, date, partial name
3. Return status="found" + target_id=<any element in that row>
4. Clicking any element in the row will select the patient!

IMPORTANT: Do NOT wait more than 2 times. After 2 waits, use partial matches or row-adjacent elements.

=== CRITICAL RULES ===

1. NEVER click on the patient row - only REPORT their ID
2. target_id MUST be a valid ID from UI_ELEMENTS list
3. After scrolling, the next step should typically be analysis (not immediate scroll again)
4. Check HISTORY to track which direction you've scrolled and what you've seen
5. Maximum 15 steps - be efficient!
6. If you've scrolled both directions and searched thoroughly, return not_found"""


USER_PROMPT = """Analyze this screenshot of the Meditech patient list (Rounds Patients).

=== CURRENT STATUS ===
Step: {current_step}/15
Patient to find: {patient_name}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== YOUR PREVIOUS ACTIONS ===
{history}

=== SCROLL STATE ===
{scroll_state}

=== INSTRUCTIONS ===

1. SEARCH for "{patient_name}" in the visible patient list
   - Names appear as "Lastname,Firstname" (e.g., "Lopez,Sarahi")
   - Match is case-insensitive
   - Look for exact or partial matches

2. IF PATIENT FOUND:
   - Find their element ID in UI_ELEMENTS
   - Return status="found" + target_id=<ID>
   - If you SEE them but can't find ID → use "wait" for OCR retry
   - After 2 waits, use ANY element in the same row (location, date, etc.)

3. IF PATIENT NOT VISIBLE:
   - Return action="scroll_down" or "scroll_up" to see more patients

REMEMBER: You only REPORT the patient's ID. You do NOT click on them.

Decide your response."""


# =============================================================================
# AGENT
# =============================================================================


class PatientFinderResult(BaseModel):
    """Structured output for PatientFinderAgent."""

    status: Literal["running", "found", "not_found", "error"] = Field(
        description="'found' when patient located, 'running' to scroll and continue, 'not_found' if entire list checked, 'error' if failed"
    )
    action: Optional[Literal["scroll_down", "scroll_up", "wait"]] = Field(
        default=None,
        description="Action to perform. Only used when status='running'. 'scroll_down'/'scroll_up' to navigate, 'wait' after scrolling or for OCR retry.",
    )
    target_id: Optional[int] = Field(
        default=None,
        description="Element ID. Only used for 'found': the patient row ID to click.",
    )
    reasoning: str = Field(
        description="Explain: What you see → What you're trying → Why this action"
    )


class PatientFinderAgent(BaseAgent):
    """
    Agent that finds a specific patient in Steward's patient list (Meditech).
    Handles scrolling through the list - searches iteratively with scroll up/down.
    Works like Baptist's PatientFinderAgent with actions, history, and loop detection.
    """

    emr_type = "steward"
    agent_name = "patient_finder"
    max_steps = 15
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
        scroll_state: str = "Not scrolled yet",
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            elements_text=elements_text,
            patient_name=patient_name,
            current_step=current_step,
            history=history,
            scroll_state=scroll_state,
        )

    def decide_action(
        self,
        patient_name: str,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
        current_step: int,
        scroll_state: str = "Not scrolled yet",
    ) -> PatientFinderResult:
        """
        Decide the next action to find the patient.

        Args:
            patient_name: Name of patient to find
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser
            history: List of previous action records
            current_step: Current step number (1-15)
            scroll_state: Description of scroll state (e.g., "Scrolled down 2 times")

        Returns:
            PatientFinderResult with action to take
        """
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
            scroll_state=scroll_state,
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
            reasoning = h.get("reasoning", "")[:300]  # Keep reasoning for context
            lines.append(f"Step {step}: {action} - {reasoning}")

        return "\n".join(lines)
