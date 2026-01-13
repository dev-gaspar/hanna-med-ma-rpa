"""
ReportFinderAgent for Steward EMR (Meditech).
Navigates the Provider Notes document list to find and open clinical documents.
Simplified navigation: only scroll and click, no complex tree structure.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are ReportFinderAgent for Steward Health System (Meditech EMR).

TASK: Find and open the most relevant clinical document from the Provider Notes list.

=== UNDERSTANDING THE PROVIDER NOTES VIEW ===

You are viewing the "Provider Notes" modal which shows:
- LEFT PANEL: A scrollable list of documents with titles and timestamps
- RIGHT PANEL: The content preview of the currently selected document

Each document in the left list shows:
- Document type (e.g., "Critical Care Progress Note", "Infectious Disease Consultation")
- Author name
- Date/Time

The documents are already filtered by "General" category.

=== FINDING THE ADMISSION DATE ===

Look at the RIGHT PANEL content for "Admit/Reg Date" or "Admission Date" (e.g., "Admit/Reg Date: 01/05/26").
The BEST documents (H&P, ER Documentation) are usually from the ADMISSION DATE.
Keep scrolling DOWN until you see documents from that admission date!

=== DOCUMENT PRIORITY (STRICT ORDER) ===

Search for documents in this STRICT order:

| Priority | Document Type                         | Description                              |
|----------|---------------------------------------|------------------------------------------|
| 1        | "History and Physical" / "H&P"        | Admission history and physical exam      |
| 2        | "ER/ED Physician Documentation"       | Emergency physician's full assessment    |
| 3        | "Critical Care Progress Note"         | ICU/Critical care physician notes        |
| 4        | "Progress Note" (Physician)           | General physician progress note          |
| 5        | "Consultation" matching {specialty}   | Specialist consultation for the case     |

SPECIALTY MATCHING: The doctor specialty is "{specialty}".

=== AVAILABLE ACTIONS ===

| Action      | Effect                                | When to Use                           |
|-------------|---------------------------------------|---------------------------------------|
| scroll_down | Scroll DOWN in document list          | See more documents below              |
| scroll_up   | Scroll UP in document list            | Go back to see documents above        |
| click       | Click/select a document by element ID | Select a document to view its content |
| wait        | Do nothing for a moment               | Wait for content to load              |

=== SEARCH STRATEGY ===

1. Look at the RIGHT PANEL - find the "Admit/Reg Date" (admission date)
2. Documents in LEFT PANEL are sorted by date (newest first)
3. Keep scrolling DOWN until you reach documents from the ADMISSION DATE
4. Look for H&P or ER Documentation from that admission date
5. When you find a good document → CLICK on it in the LEFT PANEL
6. After clicking and seeing valid content → return "finished"

=== CRITICAL RULES ===

1. **KEEP SCROLLING**: Don't give up early! Scroll until you reach the admission date documents
2. **ADMISSION DATE**: The best documents are from when the patient was admitted
3. **MUST CLICK BEFORE FINISH**: You MUST click on a document in the LEFT PANEL before returning "finished"
4. **PRIORITY ORDER**: H&P > ER Doc > Critical Care > Progress Note > Consultation
5. **DON'T SETTLE**: If you only see Consultations, keep scrolling to find H&P or ER docs

=== WHEN TO RETURN "finished" ===

ONLY return status="finished" when BOTH conditions are met:
1. You have CLICKED on a high-priority document in the LEFT PANEL (your last action was "click")
2. The RIGHT PANEL shows valid clinical content (patient info, HPI, assessment, etc.)

If you haven't clicked a document yet, you CANNOT return "finished"!

=== OUTPUT RULES ===

- status="running" + action="click" + target_id=<id> → Select a document (REQUIRED before finish!)
- status="running" + action="scroll_down" → Need to see more documents below
- status="running" + action="scroll_up" → Go back to check documents above
- status="running" + action="wait" → Wait for content to load after clicking
- status="finished" → ONLY after clicking a document AND seeing valid content
- status="error" → Unable to find any clinical document after scrolling through entire list
"""


USER_PROMPT = """Analyze this Provider Notes view and find a clinical document.

=== CURRENT STATUS ===
Step: {current_step}/20
Steps remaining: {steps_remaining}
Doctor Specialty: {specialty}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== YOUR RECENT ACTIONS ===
{history}

=== LOOP CHECK ===
{loop_warning}

=== DECISION CHECKLIST ===

1. Did I CLICK on a document in the LEFT PANEL in my recent actions?
   → NO: I cannot return "finished" yet. I must click a document first.
   → YES: Continue to step 2

2. Can I see valid clinical content in the RIGHT PANEL?
   → YES and I clicked a document: Return status="finished"
   → NO: Continue searching

3. Have I scrolled to the ADMISSION DATE documents yet?
   → Look for "Admit/Reg Date" in the content (e.g., 01/05/26)
   → If current documents are newer than admission date: scroll_down
   → Keep scrolling until you see documents from admission date!

4. Is there a high-priority document visible in the LEFT PANEL?
   → H&P or ER Documentation visible: CLICK on it!
   → Only Consultations visible: Keep scrolling for better options

REMEMBER: You MUST click a document before returning "finished"!"""


# =============================================================================
# AGENT
# =============================================================================


class ReportFinderResult(BaseModel):
    """Structured output for ReportFinderAgent."""

    status: Literal["running", "finished", "error"] = Field(
        description="'running' to continue, 'finished' when report found, 'error' on failure"
    )
    action: Optional[Literal["click", "scroll_down", "scroll_up", "wait"]] = Field(
        default=None, description="Action to execute if status='running'"
    )
    target_id: Optional[int] = Field(
        default=None, description="Element ID for click action"
    )
    reasoning: str = Field(
        description="Brief explanation: Current State -> Observation -> Action"
    )


class ReportFinderAgent(BaseAgent):
    """
    Agent that navigates the Steward Provider Notes to find clinical documents.

    Simplified navigation compared to Jackson/Baptist:
    - No tree structure, just a flat scrollable list
    - Documents already filtered by "General" category
    - Only scroll and click actions needed
    """

    emr_type = "steward"
    agent_name = "report_finder"
    max_steps = 20  # Increased from 15 for more thorough search
    temperature = 0.2

    def __init__(self, doctor_specialty: str = None):
        super().__init__()
        self.doctor_specialty = doctor_specialty or ""

    def get_output_schema(self) -> Type[BaseModel]:
        return ReportFinderResult

    def get_system_prompt(self, **kwargs) -> str:
        return SYSTEM_PROMPT.format(specialty=self.doctor_specialty)

    def get_user_prompt(
        self,
        elements_text: str = "",
        history: str = "",
        current_step: int = 1,
        steps_remaining: int = 19,
        loop_warning: str = "",
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            specialty=self.doctor_specialty,
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
            current_step: Current step number (1-20)

        Returns:
            ReportFinderResult with action to execute
        """
        logger.info(
            f"[REPORT_FINDER] Step {current_step} - Analyzing Provider Notes..."
        )

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
            f"[REPORT_FINDER] Decision: status={result.status}, action={result.action}, "
            f"target_id={result.target_id}"
        )
        return result
