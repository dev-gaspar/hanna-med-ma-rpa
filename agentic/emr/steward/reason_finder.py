"""
ReasonFinderAgent for Steward EMR (Meditech).
Finds the "Reason For Consult" by locating a Consult order matching the doctor's specialty,
clicking to expand it, and extracting the reason from the expanded details.

Works iteratively with scroll support:
1. Scrolls through Orders list to find "Consult" section
2. Clicks on Consult order matching the doctor's specialty
3. Extracts the reason from the expanded Consult details
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are ReasonFinderAgent for Steward Health System (Meditech EMR).

TASK: Find the "Reason For Consult" for a {specialty} consultation in the Orders view.

=== UNDERSTANDING STEWARD ORDERS VIEW ===

You are viewing the "Orders" section of a patient's chart in Meditech.
The Orders view shows a scrollable list organized by category sections (all expanded by default):
- Transfer
- Admit-Discharge-Transfer  
- Consult (THIS IS WHERE YOU LOOK)
- Medications
- Diet
- Activity
- etc.

All sections are ALREADY EXPANDED (arrow ∨ pointing down). You can see all orders directly.

Each order row shows:
- Order Name (e.g., "Consult [Podiatry/Foot and Ankle Surgery] Routine")
- Provider name
- Date/Time
- Status (Ordered, Active, etc.)
- Blue info icon (i) on the right

=== YOUR MISSION ===

1. SCAN the Orders list for a Consult order matching "{specialty}"
2. CLICK on that Consult order row to expand its details
3. After clicking, LOOK for "Comment:" text in the expanded details
4. EXTRACT and REPORT the reason text after "Comment:"

=== SPECIALTY MATCHING ===

The doctor specialty is: "{specialty}"

When searching for matching Consult orders, look for:
- Exact specialty name (e.g., "Podiatry" for Podiatry specialty)
- Related terms (e.g., "Foot and Ankle" for Podiatry)
- Partial matches are OK if clearly related

Examples of Consult orders you might see:
- "Consult [Podiatry/Foot and Ankle Surgery] Routine" → matches Podiatry
- "Consult [Cardiology] Urgent" → matches Cardiology  
- "Consult [Orthopedic Surgery] Routine" → matches Orthopedics

=== AVAILABLE ACTIONS ===

| Status      | Action        | Effect                                               |
|-------------|---------------|------------------------------------------------------|
| running     | scroll_down   | Scroll DOWN to find Consult section                  |
| running     | scroll_up     | Scroll UP if you went past Consult section           |
| running     | click         | Click on element by ID (Consult order to expand)     |
| running     | wait          | Wait for screen to load / after clicking             |
| found       | -             | Reason extracted! Return reason_text                 |
| not_found   | -             | No matching Consult found after full search          |

=== SEARCH STRATEGY ===

Phase A - Find Matching Consult:
1. Scan current view for Consult orders (sections are already expanded)
2. Look for order text containing "{specialty}" or related terms
3. If not visible, scroll DOWN to see more orders
4. If matching Consult found → action="click" with target_id=<element_id>

Phase B - Extract Reason:
5. After clicking, wait for details to expand (use action="wait")
6. Look for "Comment:" text - the reason appears AFTER this label
7. Example: "Comment: RN to call Adm Phys for inpatient orders" → reason is "RN to call Adm Phys for inpatient orders"
8. If reason visible → status="found" + reason_text="<the reason>"

=== OUTPUT RULES ===

- status="running" + action="scroll_down"
  → Consult section not visible, scroll to find it
  
- status="running" + action="scroll_up"  
  → Went past Consult section, scroll back up

- status="running" + action="click" + target_id=<element_id>
  → Found matching Consult order, click to expand
  
- status="running" + action="wait"
  → Just clicked, waiting for details to load

- status="found" + reason_text="<reason>"
  → Reason extracted from expanded Consult details

- status="not_found"
  → Entire Orders list searched, no matching Consult found

=== DETECTING END OF LIST ===

- If you see the SAME orders after scrolling, you've reached the end
- If bottom AND top reached without finding Consult → not_found

=== IMPORTANT NOTES ===

1. All category sections are already expanded - orders are visible directly
2. After clicking a Consult order, details appear BELOW the order row
3. Look for "Comment:" label followed by the reason text
4. The reason may span multiple lines - capture the full text
5. Use "wait" ONCE after clicking to let the UI update
"""


USER_PROMPT = """CURRENT ORDERS VIEW ANALYSIS

Specialty to find: {specialty}

Current scroll state: {scroll_state}

=== UI ELEMENTS DETECTED ===
{elements_text}

=== PREVIOUS ACTIONS (last 5) ===
{history_text}

=== YOUR DECISION ===

Based on the current Orders view:
1. Can you see a Consult order matching "{specialty}"?
2. If you already clicked a Consult, can you see "Comment:" with the reason?

Decide your next action."""


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class ReasonFinderResult(BaseModel):
    """Structured output for ReasonFinderAgent."""

    status: Literal["running", "found", "not_found", "error"] = Field(
        description="'running' to continue, 'found' when reason extracted, 'not_found' if exhausted, 'error' on failure"
    )
    action: Optional[Literal["click", "scroll_down", "scroll_up", "wait"]] = Field(
        default=None, description="Action to execute if status='running'"
    )
    target_id: Optional[int] = Field(
        default=None, description="Element ID for click action"
    )
    reason_text: Optional[str] = Field(
        default=None,
        description="Extracted reason/comment text. Only set if status='found'",
    )
    reasoning: str = Field(description="Brief explanation of decision for debugging")


# =============================================================================
# AGENT CLASS
# =============================================================================


class ReasonFinderAgent(BaseAgent):
    """
    Agent that finds the Reason For Consult in Steward's Orders view.

    Works iteratively with scroll support:
    1. Scrolls to find the Consult section
    2. Clicks on a Consult order matching the doctor's specialty
    3. Extracts the reason from the expanded details (Comment: text)
    """

    emr_type = "steward"
    agent_name = "reason_finder"
    max_steps = 15
    temperature = 0.2

    def __init__(self, specialty: str = ""):
        super().__init__()
        self.specialty = specialty

    def get_output_schema(self) -> Type[BaseModel]:
        return ReasonFinderResult

    def get_system_prompt(self, **kwargs) -> str:
        return SYSTEM_PROMPT.format(specialty=self.specialty)

    def get_user_prompt(
        self,
        elements_text: str = "",
        scroll_state: str = "Not scrolled yet",
        history_text: str = "",
        **kwargs,
    ) -> str:
        return USER_PROMPT.format(
            specialty=self.specialty,
            scroll_state=scroll_state,
            elements_text=elements_text,
            history_text=history_text,
        )

    def decide_action(
        self,
        elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
        scroll_state: str,
        image_base64: str = "",
    ) -> ReasonFinderResult:
        """
        Decide next action based on current screen state.

        Args:
            elements: Parsed UI elements from OmniParser
            history: Previous actions taken
            scroll_state: Description of scroll position
            image_base64: Base64 encoded screenshot

        Returns:
            ReasonFinderResult with action decision
        """
        logger.info(f"[REASON_FINDER] Looking for {self.specialty} consult...")

        # Format elements using BaseAgent utility
        elements_text = self.format_ui_elements(elements)

        # Format history
        history_text = self._format_history(history)

        result = self.invoke(
            image_base64=image_base64,
            elements_text=elements_text,
            scroll_state=scroll_state,
            history_text=history_text,
        )

        logger.info(
            f"[REASON_FINDER] Decision: status={result.status}, action={result.action}, "
            f"target_id={result.target_id}, reason={result.reason_text[:40] + '...' if result.reason_text and len(result.reason_text) > 40 else result.reason_text}"
        )
        return result

    def _format_history(self, history: List[Dict[str, Any]]) -> str:
        """Format action history for the prompt."""
        if not history:
            return "No previous actions (first step)"

        lines = []
        for h in history[-5:]:  # Last 5 actions
            step = h.get("step", "?")
            action = h.get("action", "?")
            reasoning = h.get("reasoning", "")[:60]
            lines.append(f"Step {step}: {action} - {reasoning}")

        return "\n".join(lines)
