"""
ReportFinderAgent for Baptist EMR.
Navigates the notes/documents tree to find and open a patient report.
Uses tools to interact with the UI: nav_up, nav_down, click, dblclick, scroll_up, scroll_down.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are ReportFinderAgent for Baptist Health EMR (Cerner PowerChart).

YOUR MISSION: Find and open the MOST RECENT valid clinical report from the Notes tree.

=============================================================================
PHASE 1: SCAN - Scroll to see all available folders
=============================================================================

FIRST, you must SCAN the tree to see what folders are available:

1. Start at the top of the Notes tree
2. Use scroll_down (repeat=3) to reveal folders below
3. Keep track of which priority folders you see:
   - Priority 1: "History and Physical Notes"
   - Priority 2: "ER/ED Notes" or "ED Notes"  
   - Priority 3: "Hospitalist Notes"
   - Priority 4: "Consultation Notes" (prefer sub-folder matching specialty)
   - Priority 5 (LAST): "Progress Notes", "Admission Notes"

4. Continue scrolling until you've seen all folders or found Priority 1

=== SPECIALTY SUB-FOLDER SEARCH STRATEGY ===

When entering Priority 4-5 folders (Consultation or Progress Notes):
1. DBLCLICK to expand the parent folder
2. SCAN all visible sub-folders for specialty match (e.g., "Podiatry", doctor's specialty)
3. If specialty sub-folder FOUND → CLICK to select, DBLCLICK to expand, then NAV_DOWN
4. If specialty sub-folder NOT FOUND:
   - In Consultation Notes → CLOSE folder, move to Progress Notes
   - In Progress Notes → Accept any Physician Progress Note (most recent first)
   - CRITICAL: If you see a sub-folder ALSO named "Progress Notes" inside the parent "Progress Notes" folder, IGNORE IT - this is the Nurse notes folder. Only explore it as ABSOLUTE LAST RESORT after exhausting ALL other options

PROGRESS NOTES PRIORITY WITHIN THE FOLDER:
- FIRST: Look for sub-folder matching doctor's specialty
- SECOND: Look for "Physician Progress Note" documents (skip anything with "Nurse")
- ABSOLUTE LAST RESORT: Only check "Progress Notes" sub-folder (Nurse) if nothing else found

FALLBACK DOCUMENTS (when no specialty found):
When no specialty-specific content is available, these are GOOD alternatives:
- "Physician Progress Note" - general but valuable physician documentation
- "Critical Care Progress Note" - comprehensive physician notes with full clinical assessment

=== CRITICAL NAVIGATION RULES ===

**WITHIN a sub-folder:** nav_down/nav_up with repeat > 1 is OK to browse consecutive documents
**BETWEEN different sub-folders:** NEVER use nav_down/nav_up to jump - you WILL get lost

TO NAVIGATE TO A DOCUMENT IN A DIFFERENT SUB-FOLDER:
1. CLICK on the target sub-folder to SELECT it
2. DBLCLICK to EXPAND it (if collapsed)  
3. NAV_DOWN to enter the sub-folder's documents

WRONG: Using nav_down repeat=3 to "count" and jump from SubFolder-A to SubFolder-B
CORRECT: CLICK on SubFolder-B, then DBLCLICK to expand, then NAV_DOWN to browse

IF YOU SEE THE TARGET DOCUMENT IN THE TREE:
- CLICK directly on that document's parent sub-folder
- Then NAV_DOWN until you reach the document
- OR DBLCLICK on the document directly to open it

CONSULTATION NOTES: If no specialty sub-folder exists → move to Progress Notes
PROGRESS NOTES: First look for specialty sub-folder, then accept Physician Progress Notes

=============================================================================
PHASE 2: EVALUATE - Identify the highest priority folder visible
=============================================================================

After scanning, identify the HIGHEST PRIORITY folder you saw:

- If you see "History and Physical Notes" → This is Priority 1, go to Phase 3
- If no Priority 1 but see "ED Notes" → This is Priority 2, go to Phase 3
- If no Priority 1-2 but see "Hospitalist Notes" → Priority 3, go to Phase 3
- Continue down the priority list...

NEVER skip to a lower priority if a higher one exists!

=============================================================================
PHASE 3: NAVIGATE - Open folder and browse documents
=============================================================================

FOLDER NAVIGATION RULES:
- PARENT FOLDERS (Priority 1-5 main folders): Use DBLCLICK to expand/collapse
- SUB-FOLDERS (specialty folders inside parent): Use CLICK to select, then DBLCLICK to expand
- DOCUMENTS (inside sub-folders): Use NAV_DOWN to move through documents within that sub-folder

STEP BY STEP:
1. DBLCLICK on parent folder to EXPAND it (reveals sub-folders)
2. CLICK on the desired sub-folder to SELECT it (matching specialty if available)
3. DBLCLICK on selected sub-folder to EXPAND it (reveals documents)
4. NAV_DOWN to select documents inside the sub-folder
5. CHECK the right pane:
   - Valid clinical content visible → status="finished" ✓
   - "23 Hour..." folder → IGNORE IT completely, don't enter it
   - Sub-folder exhausted → DBLCLICK to CLOSE, try next sub-folder
6. If parent folder exhausted → DBLCLICK to CLOSE, go to next priority

CRITICAL: If you want to reach a document in a DIFFERENT sub-folder, DON'T use nav_down
to jump across sub-folders. Instead, CLICK on that sub-folder first, then navigate within it.

=============================================================================
CRITICAL: HIERARCHICAL NAVIGATION & DATE LOGIC
=============================================================================

When you open a folder (e.g. "Progress Notes"):
1. PAUSE. Look at the children elements.
2. If you see SUB-FOLDERS (e.g. "Neurology", "Infectious Disease"):
   - Don't just click the first one!
   - Scan for the most relevant specialty (e.g. General Medicine, Hospitalist).
   - If unsure, "General" or blank is usually best.
3. If you see DOCUMENTS:
   - READ THE DATES. (e.g. "01/05/26", "12/30/25")
   - YOU MUST NAVIGATE TO THE MOST RECENT DOCUMENT.
   - Do not settle for an old note just because it's first in the list.

=============================================================================
AVAILABLE ACTIONS
=============================================================================

| Action      | Purpose                                          | When to Use                    |
|-------------|--------------------------------------------------|--------------------------------|
| scroll_down | Scroll tree DOWN to reveal folders below         | PHASE 1: Scanning for folders  |
| scroll_up   | Scroll tree UP to reveal folders above           | If you scrolled too far        |
| click       | Click on a visible element                       | To select a folder             |
| dblclick    | Double-click on element                          | To expand/collapse folder      |
| nav_down    | Move selection DOWN and auto-open document       | PHASE 3: Inside expanded folder|
| nav_up      | Move selection UP and auto-open document         | PHASE 3: Inside expanded folder|
| wait        | Do nothing, wait for OCR refresh                 | If OCR missed an element       |

=============================================================================
CRITICAL RULES
=============================================================================

1. scroll_down/scroll_up = For finding FOLDERS (Phase 1)
2. nav_down/nav_up = For browsing DOCUMENTS inside a folder (Phase 3)
3. NEVER use nav_down to find folders - it enters documents, not scrolls!
4. Once you SEE a priority folder → CLICK on it, don't nav towards it!
5. nav_down/nav_up AUTO-OPEN documents - check right pane after each nav

=============================================================================
WHAT TO SKIP
=============================================================================

- **"Progress Notes" sub-folder inside "Progress Notes"** - This is the Nurse notes folder! IGNORE IT unless absolutely nothing else is available
- "23 Hour History and Physical Update Note" - brief update, not full H&P
- "Nurse Progress Note" or any note with "Nurse" in the name - prefer Physician notes
- "Progress Note Nurse" - SKIP, look for "Progress Note" without "Nurse" suffix
- "Consultation Note" - ONLY accept if priorities 1-4 have no documents
- Documents with no visible clinical content

=============================================================================
WHEN TO CLOSE FOLDERS
=============================================================================

If the tree looks chaotic (many folders expanded):
→ Use dblclick to CLOSE unnecessary folders
→ This simplifies navigation

=============================================================================
FOLDER EXPLORATION MEMORY
=============================================================================

CRITICAL: When you try a folder and find ONLY skip-documents (like "23 Hour..."):
- That folder is EXHAUSTED for the current priority
- Mark it mentally as "checked - no valid docs"
- NEVER return to that folder in subsequent steps
- Move IMMEDIATELY to the next priority folder

EXAMPLE:
- Step 5: Entered "History and Physical Notes" → only "23 Hour..." docs
- MARK: H&P = exhausted, proceed to Priority 2
- Steps 6-30: NEVER click on "History and Physical Notes" again

=============================================================================
MISSING FOLDER HANDLING
=============================================================================

Not all patients have all folder types. If after 2 scroll actions you don't see:
- "ER/ED Notes" or "ED Notes" → SKIP Priority 2, go to Priority 3
- "Hospitalist Notes" → SKIP Priority 3, go to Priority 4
- "Progress Notes" → SKIP Priority 4, go to Priority 5 (Consultation)

DO NOT:
- Scroll more than 2 times looking for a single folder
- Assume a folder exists just because it's in the priority list
- Keep searching for folders that aren't visible after reasonable scrolling

=============================================================================
SUCCESS CRITERIA
=============================================================================

Return status="finished" when the RIGHT PANE shows valid clinical content:
- Chief Complaint, History of Present Illness, Assessment, Plan, etc.
- Physical Exam findings, Review of Systems, etc.

=============================================================================
ERROR CONDITIONS
=============================================================================

Return status="error" when:
- You are NOT in the Notes tree view (wrong screen)
- All priority folders have been tried with no valid documents
- Past step 28 with no valid document found

=============================================================================
OUTPUT FORMAT
=============================================================================

{{
  "status": "running" | "finished" | "error",
  "action": "scroll_down" | "scroll_up" | "click" | "dblclick" | "nav_down" | "nav_up" | "wait",
  "target_id": <element_id for click/dblclick, null otherwise>,
  "repeat": <1-5 for scroll/nav actions>,
  "reasoning": "Phase X: What I see → What I'm doing → Why"
}}"""


USER_PROMPT = """=== DOCTOR'S SPECIALTY ===
{doctor_specialty}

=== CURRENT STATUS ===
Step: {current_step}/30
Steps remaining: {steps_remaining}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== YOUR RECENT ACTIONS ===
{history}

=== LOOP WARNING ===
{loop_warning}

Decide your next action."""


# =============================================================================
# AGENT
# =============================================================================


class ReportFinderResult(BaseModel):
    """Structured output for ReportFinderAgent."""

    status: Literal["running", "finished", "error"] = Field(
        description="'running' to continue, 'finished' when report found, 'error' if failed"
    )
    action: Optional[
        Literal[
            "click",
            "dblclick",
            "nav_up",
            "nav_down",
            "scroll_up",
            "scroll_down",
            "wait",
        ]
    ] = Field(
        default=None, description="Action to perform. Required if status='running'"
    )
    target_id: Optional[int] = Field(
        default=None,
        description="Element ID to click/dblclick. Required for click/dblclick actions",
    )
    repeat: Optional[int] = Field(
        default=1,
        description="Number of times to repeat scroll/nav actions (1-5). Default 1.",
        ge=1,
        le=5,
    )
    reasoning: str = Field(
        description="Phase X: What you see → What you're doing → Why"
    )


class ReportFinderAgent(BaseAgent):
    """
    Agent that navigates the Notes tree to find a clinical report.
    Uses a 3-phase approach: SCAN → EVALUATE → NAVIGATE.
    """

    emr_type = "baptist"
    agent_name = "report_finder"
    max_steps = 30
    temperature = 0.3

    def __init__(self, doctor_specialty: str = None):
        super().__init__()
        self.doctor_specialty = doctor_specialty

    def get_output_schema(self) -> Type[BaseModel]:
        return ReportFinderResult

    def get_system_prompt(self, **kwargs) -> str:
        return SYSTEM_PROMPT

    def get_user_prompt(
        self,
        elements_text: str = "",
        current_step: int = 0,
        history: str = "",
        **kwargs,
    ) -> str:
        """Generate user prompt with labeled input data only."""
        steps_remaining = self.max_steps - current_step
        loop_warning = self._detect_loop_from_text(history)

        return USER_PROMPT.format(
            doctor_specialty=self.doctor_specialty,
            current_step=current_step,
            steps_remaining=steps_remaining,
            elements_text=elements_text or "No elements detected",
            history=history or "No previous actions",
            loop_warning=loop_warning,
        )

    def _detect_loop_from_text(self, history: str) -> str:
        """Detect if agent is in a loop from history text."""
        if not history:
            return "No loop detected - this is step 1."

        # Count actions in text
        nav_down_count = history.lower().count("nav_down")
        nav_up_count = history.lower().count("nav_up")
        scroll_count = history.lower().count("scroll")

        if nav_down_count >= 3 and scroll_count == 0:
            return "WARNING: Multiple nav_down without scroll. If folder not visible, use scroll_down first!"
        if nav_up_count >= 3:
            return "WARNING: Multiple nav_up. Consider closing folder and trying next priority."
        if nav_down_count >= 2 and nav_up_count >= 2:
            return "WARNING: Alternating nav_up/nav_down. STOP and use scroll_down to find folders!"

        return "No loop detected."

    def _format_history(self, history: List[Dict[str, Any]]) -> str:
        """Format action history for the prompt."""
        if not history:
            return "No previous actions."

        lines = []
        for h in history[-10:]:  # Last 10 actions
            step = h.get("step", "?")
            action = h.get("action", "?")
            reasoning = h.get("reasoning", "")[:500]  # Keep more reasoning for context
            lines.append(f"Step {step}: {action} - {reasoning}")

        return "\n".join(lines)

    def decide_action(
        self,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
        current_step: int,
        **kwargs,
    ) -> ReportFinderResult:
        """
        Decide the next action to find the report.

        Args:
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser
            history: List of previous action records
            current_step: Current step number

        Returns:
            ReportFinderResult with action to take
        """
        logger.info(f"[REPORT_FINDER] Step {current_step} - analyzing screen...")

        # Format elements using base class method
        elements_text = self.format_ui_elements(ui_elements)

        # Format history
        history_text = self._format_history(history)

        result = self.invoke(
            image_base64=image_base64,
            elements_text=elements_text,
            current_step=current_step,
            history=history_text,
        )

        logger.info(
            f"[REPORT_FINDER] Decision: {result.status}, action={result.action}, target={result.target_id}"
        )
        return result
