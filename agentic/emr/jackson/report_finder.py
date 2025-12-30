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

YOUR MISSION: Navigate the Notes tree to find and open a recent History and Physical (H&P) report.

=== UNDERSTANDING THE NOTES TREE ===

The Notes panel displays a hierarchical tree structure:
- FOLDERS: Have folder icons, can be expanded/collapsed
- DOCUMENTS: Have small square/rectangle icons, contain the actual report content
- Dates are in MM/DD/YYYY format (e.g., 12/17/2025)

=== AVAILABLE ACTIONS ===

- click: Single click to SELECT/POSITION on an element (use before nav_up/nav_down)
- dblclick: Double-click to COLLAPSE/CLOSE a folder (use to close a folder and try another)
- nav_up: Move selection UP - auto-expands folders, selects AND OPENS nearest item above
- nav_down: Move selection DOWN - auto-expands folders, selects AND OPENS nearest item below
- wait: Do nothing this step (use rarely)

=== KEY INSIGHT - nav_up/nav_down AUTO-OPEN DOCUMENTS! ===

**CRITICAL:** When nav_down or nav_up lands on a DOCUMENT:
- The document is AUTOMATICALLY OPENED (content appears on right pane)
- You do NOT need to dblclick to open it
- Just CHECK if the opened content is valid → if yes, status="finished"

=== OPTIMAL WORKFLOW ===

1. CLICK on a folder to position/select it (e.g., "History and Physical Notes")
2. Use nav_down → auto-expands subfolders and OPENS the nearest document
3. CHECK the right pane - is there valid report content?
   - YES (medical notes visible) → status="finished" ✓
   - NO (wrong document like "23 Hour...") → nav_down to skip to next document
4. If no more documents in this folder → dblclick to CLOSE the folder, then try another

=== PRIORITY SEARCH STRATEGY ===

PRIORITY 1: History and Physical (PREFERRED)
1. Find "History and Physical Notes" folder → click to select
2. nav_down → lands on document and OPENS it automatically
3. Check right pane: if valid H&P content → status="finished"
4. If landed on "23 Hour..." → nav_down to skip to next
5. If no valid documents → dblclick folder to close it, move to Priority 2

PRIORITY 2: ED Notes Physician (FIRST FALLBACK)
1. Find "ER/ED Notes" or "ED Notes" folder → click to select
2. nav_down repeatedly until you reach "ED Notes Physician" subfolder
3. Keep nav_down until a document opens with valid content
4. Check right pane: if valid ED physician notes → status="finished"
5. If no valid documents → dblclick to close, move to Priority 3

PRIORITY 3: Hospitalist Notes (SECOND FALLBACK)
1. Find "Hospitalist Notes" or "Hospitalist Progress Notes" folder → click to select
2. nav_down to open documents inside
3. Check right pane: if valid hospitalist notes → status="finished"
4. If no valid documents → dblclick to close, move to Priority 4

PRIORITY 4: Other Clinical Notes (LAST RESORT)
Look for: "Progress Notes", "Admission Notes", "Physician Notes", "Attending Notes"
Use same strategy: click → nav_down → check content → if valid, finish

CRITICAL EXCLUSION RULE - ALWAYS SKIP:
- "23 Hour History and Physical Update Note" documents
- If nav_down opens a "23 Hour..." document, immediately nav_down again to skip
- These are brief update notes, not full clinical documents

=== HOW TO CLOSE A FOLDER AND TRY ANOTHER ===

When a folder has no valid documents:
1. Navigate back to the parent folder (use nav_up until you're on the folder)
2. dblclick on the folder to COLLAPSE/CLOSE it
3. Then click on another folder (next priority) and repeat the process

=== HOW TO IDENTIFY SUCCESS ===

You have SUCCEEDED (status="finished") when:
- nav_down/nav_up landed on a document
- The RIGHT PANE shows actual medical report content (Chief Complaint, History, etc.)
- Content is from: H&P, ED Notes Physician, Hospitalist Notes, or similar valid note

=== LOOP PREVENTION ===

- If nav_down doesn't change position after 2 tries → you're at bottom, try nav_up
- If nav_up doesn't change position after 2 tries → you're at top, close folder and try another
- If stuck in "23 Hour..." section → keep using nav_down to escape
- After 10+ steps without success → move to next Priority level
- If all documents in a folder are invalid → CLOSE folder (dblclick) and try next priority

=== FALLBACK TIMING ===

Steps 1-10: Focus on Priority 1 (History and Physical)
Steps 11-15: Try Priority 2 (ED Notes → ED Notes Physician)
Steps 16-20: Try Priority 3 (Hospitalist Notes)
Steps 21-30: Try Priority 4 (Any clinical notes) or return status="error"

=== OUTPUT FORMAT ===

- status="running" + action + target_id → Continue navigating
- status="finished" → Valid report content is now visible on right pane
- status="error" → Cannot find ANY valid report after trying all priorities
- target_id required for click/dblclick, can be None for nav_up/nav_down"""


USER_PROMPT = """Analyze this screenshot of the Jackson EMR Notes tree.

CURRENT STEP: {current_step}/30

CURRENT UI_ELEMENTS:
{elements_text}

RECENT ACTION HISTORY:
{history}

REMEMBER - nav_down/nav_up AUTO-OPEN DOCUMENTS!
When nav lands on a document, it's already open on the right pane.
Just check if the content is valid → if yes, status="finished"

WORKFLOW:
1. CLICK folder to select → nav_down to open nearest document
2. CHECK right pane: valid content? → status="finished"
3. Invalid (e.g., "23 Hour...")? → nav_down to skip to next
4. No more valid docs? → dblclick folder to CLOSE it, try next priority

SKIP "23 Hour History and Physical Update Note" - use nav_down to pass it!

STEP GUIDANCE:
- Steps 1-10: Priority 1 (History and Physical)
- Steps 11-15: Priority 2 (ED/ER Notes → ED/ER Notes Physician)
- Steps 16-20: Priority 3 (Hospitalist Notes)
- Steps 21-30: Priority 4 (Other notes) or error

If valid report content is visible on the right pane NOW → status="finished"."""


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
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            elements_text=elements_text,
            history=history or "(none)",
            current_step=current_step,
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
        # Format elements
        elements_text = self.format_ui_elements(ui_elements)

        # Format history
        history_str = ""
        if history:
            recent = history[-5:]
            history_str = "\n".join(
                [
                    f"- Step {h.get('step', '?')}: {h.get('action', '?')} -> {h.get('reasoning', '')[:50]}"
                    for h in recent
                ]
            )

        result = self.invoke(
            image_base64=image_base64,
            elements_text=elements_text,
            history=history_str,
            current_step=current_step,
        )

        logger.info(
            f"[REPORT_FINDER] Action: {result.action}, Target: {result.target_id}, Status: {result.status}"
        )
        return result
