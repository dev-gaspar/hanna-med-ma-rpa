"""
ReportFinderAgent for Jackson EMR.
Navigates the notes tree to find and open a patient report.
Uses tools to interact with the UI: nav_up, nav_down, click, dblclick.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are ReportFinderAgent for Jackson Hospital EMR (Cerner PowerChart).

YOUR MISSION: Navigate the Notes tree to find and open a clinical report with valid content.

=== UNDERSTANDING THE NOTES TREE ===

The Notes panel displays a hierarchical tree structure:
- FOLDERS: Have folder icons (yellow/brown), can be expanded/collapsed by double-click
- DOCUMENTS: Have document icons (small rectangle), contain actual report content
- The SELECTED item is highlighted (usually blue background)
- The RIGHT PANE shows the content of the currently opened document

=== AVAILABLE ACTIONS ===

| Action    | Effect                                           | When to Use                        |
|-----------|--------------------------------------------------|-------------------------------------|
| click     | Select an element (positions cursor)             | Before nav_up/nav_down on a folder  |
| dblclick  | Toggle folder open/close                         | To CLOSE a folder and try another   |
| nav_up    | Move selection UP, auto-opens documents          | Navigate within expanded folder     |
| nav_down  | Move selection DOWN, auto-opens documents        | Navigate within expanded folder     |
| wait      | Do nothing                                       | Rarely needed                       |

=== CRITICAL BEHAVIOR OF nav_up/nav_down ===

When nav_down or nav_up lands on a DOCUMENT:
- The document is AUTOMATICALLY OPENED in the right pane
- You do NOT need to dblclick - just CHECK if content is valid
- Valid content = medical notes (Chief Complaint, History, Assessment, etc.)

=== PRIORITY SEARCH ORDER ===

Search folders in this order. Move to next priority if current has no valid documents:

| Priority | Folder Name                        | Valid Documents Inside                |
|----------|------------------------------------|---------------------------------------|
| 1        | "History and Physical Notes"       | Any H&P (SKIP "23 Hour..." docs)      |
| 2        | "ER/ED Notes" or "ED Notes"        | "ED Notes Physician" specifically     |
| 3        | "Hospitalist Notes"                | Any hospitalist note                  |
| 4        | "Progress Notes", "Admission Notes"| Any clinical note with content        |

=== WORKFLOW FOR EACH PRIORITY ===

1. CLICK on the target folder to select it
2. Use nav_down to enter the folder and open the first document
3. CHECK the right pane:
   - Valid content visible → status="finished" ✓
   - "23 Hour..." or empty → nav_down to try next document
   - No more documents → dblclick folder to CLOSE, go to next priority
4. If stuck in same position after 2 nav actions → folder is exhausted, close it

=== DOCUMENTS TO ALWAYS SKIP ===

- "23 Hour History and Physical Update Note" - brief update, not full H&P
- Documents with no visible content in right pane
- Administrative or non-clinical documents

=== LOOP DETECTION - CRITICAL ===

You are in a LOOP if:
- Same action (nav_up or nav_down) repeated 3+ times without progress
- Alternating between nav_up and nav_down without finding documents
- Same folder being clicked repeatedly

ESCAPE STRATEGIES:
1. If nav_down stuck → try nav_up once, then CLOSE folder (dblclick) and try next priority
2. If nav_up stuck → try nav_down once, then CLOSE folder and try next priority
3. If alternating nav_up/nav_down → STOP, close folder, move to NEXT PRIORITY
4. After step 15 without success → skip directly to Priority 3 or 4

=== SUCCESS CRITERIA ===

Return status="finished" when:
- A document is open (landed on it via nav_up/nav_down or was already open)
- The RIGHT PANE shows actual clinical content (History, Physical Exam, Assessment, Plan, etc.)
- The document is NOT a "23 Hour..." update note

=== WHEN TO RETURN error ===

Return status="error" only when:
- All 4 priority folders have been tried and exhausted
- You're past step 25 with no valid document found
- The Notes tree appears empty or inaccessible

=== OUTPUT REQUIREMENTS ===

- status="running" + action + target_id (for click/dblclick) → Continue navigating
- status="finished" → Valid report is now visible
- status="error" → No valid report found after exhausting all options
- reasoning MUST explain: What you see → What you're trying → Why this action"""


USER_PROMPT = """Analyze this screenshot of the Jackson EMR Notes tree.

=== CURRENT STATUS ===
Step: {current_step}/30
Steps remaining: {steps_remaining}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== YOUR RECENT ACTIONS ===
{history}

=== LOOP CHECK ===
{loop_warning}

=== DECISION CHECKLIST ===
1. Is there valid clinical content visible in the RIGHT PANE now?
   → YES: Return status="finished"
   → NO: Continue to step 2

2. Am I repeating the same action without progress (loop)?
   → YES: CLOSE current folder (dblclick), try next priority folder
   → NO: Continue current strategy

3. Which priority folder should I be working on based on current step?
   - Steps 1-10: Priority 1 (History and Physical Notes)
   - Steps 11-17: Priority 2 (ED/ER Notes)
   - Steps 18-24: Priority 3 (Hospitalist Notes)
   - Steps 25-30: Priority 4 (Any clinical notes) or error

4. What is my next action to make progress?
   → If need to select folder: click on folder element
   → If inside folder, need next doc: nav_down
   → If at bottom of folder: nav_up to folder, then dblclick to close
   → If folder exhausted: close it, click on next priority folder

REMEMBER: nav_down/nav_up AUTO-OPEN documents. Check right pane after each nav action!"""


# =============================================================================
# AGENT
# =============================================================================


class ReportFinderResult(BaseModel):
    """Structured output for ReportFinderAgent."""

    status: Literal["running", "finished", "error"] = Field(
        description="'running' to continue, 'finished' when report found, 'error' on failure"
    )
    action: Optional[Literal["click", "dblclick", "nav_up", "nav_down", "wait"]] = (
        Field(default=None, description="Action to execute")
    )
    target_id: Optional[int] = Field(
        default=None, description="Element ID for click/dblclick actions"
    )
    reasoning: str = Field(
        description="Brief explanation: Current State -> Observation -> Action"
    )


class ReportFinderAgent(BaseAgent):
    """
    Agent that navigates the Jackson notes tree to find a report.

    Uses a tool-based approach where the agent decides which action to take
    and the runner executes it.
    """

    emr_type = "jackson"
    agent_name = "report_finder"
    max_steps = 30
    temperature = 0.2

    def get_output_schema(self) -> Type[BaseModel]:
        return ReportFinderResult

    def get_system_prompt(self, **kwargs) -> str:
        return SYSTEM_PROMPT

    def get_user_prompt(
        self,
        elements_text: str = "",
        history: str = "",
        current_step: int = 1,
        steps_remaining: int = 29,
        loop_warning: str = "",
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            elements_text=elements_text,
            history=history or "(No previous actions)",
            current_step=current_step,
            steps_remaining=steps_remaining,
            loop_warning=loop_warning or "No loop detected.",
        )

    def decide_action(
        self,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]] = None,
        current_step: int = 1,
    ) -> ReportFinderResult:
        """
        Decide the next action based on current screen state.

        Args:
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser
            history: Recent action history for loop prevention
            current_step: Current step number (1-30)

        Returns:
            ReportFinderResult with action to execute
        """
        # Format elements using BaseAgent utility
        elements_text = self.format_ui_elements(ui_elements)

        # Calculate steps remaining
        steps_remaining = self.max_steps - current_step

        # Detect loops using BaseAgent utility
        _, loop_warning = self.detect_loop(history) if history else (False, "")

        # Format history using BaseAgent utility
        history_str = self.format_history(history) if history else ""

        result = self.invoke(
            image_base64=image_base64,
            elements_text=elements_text,
            history=history_str,
            current_step=current_step,
            steps_remaining=steps_remaining,
            loop_warning=loop_warning,
        )

        logger.info(
            f"[REPORT_FINDER] Action: {result.action}, Target: {result.target_id}, Status: {result.status}"
        )
        return result
