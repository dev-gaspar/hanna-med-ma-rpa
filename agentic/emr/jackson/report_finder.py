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
- FOLDERS: Have folder icons, can be expanded/collapsed with dblclick
- DOCUMENTS: Have small square/rectangle icons, contain the actual report content
- Dates are in MM/DD/YYYY format (e.g., 12/17/2025)

Tree structure example:
```
History and Physical Notes (folder)
└── History and Physical (folder)
    └── History and Physical (folder)
        ├── 12/17/2025 (document) ← GOAL: Open this recent H&P
        ├── 06/16/2024 (document)
        └── 06/11/2024 (document)
    └── 23 Hour History and Physical Update Note (folder) ← AVOID THIS
        └── documents...
```

=== AVAILABLE ACTIONS ===

- click: Single click to position/focus on an element (hover over a folder before selecting)
- dblclick: Double-click to OPEN a folder (expand tree) or OPEN a document (view content)
- nav_up: Scroll the tree UP to see items above current view
- nav_down: Scroll the tree DOWN to see items below current view
- wait: Do nothing this step (use rarely)

=== PRIORITY SEARCH STRATEGY ===

PRIORITY 1: History and Physical Notes → History and Physical
1. Find "History and Physical Notes" folder → dblclick to open
2. Find "History and Physical" subfolder → dblclick to open
3. Look inside for documents (dates like MM/DD/YYYY)
4. Find the MOST RECENT document → dblclick to open
5. When report content is visible on the right pane → status="finished"

CRITICAL EXCLUSION RULE:
- DO NOT use documents inside "23 Hour History and Physical Update Note" folder
- If you see "23 Hour..." or "23-Hour Update Note", this is NOT what we want
- If ONLY "23 Hour..." documents exist, proceed to PRIORITY 2

PRIORITY 2: ER/ED Notes Physician (if H&P not found or only has 23-Hour notes)
1. Go back to main level (you may need to scroll up or find parent folders)
2. Find "ER/ED Notes" or "ED Notes Physician" folder → dblclick to open
3. Find most recent document → dblclick to open
4. When report content is visible → status="finished"

=== TREE NAVIGATION RULES ===

1. ALWAYS dblclick on the folder/document TEXT, NOT on [+]/[-] icons
2. If a folder is already expanded (shows children), navigate INTO it
3. Look for the MOST RECENT date (highest year, then month, then day)
4. Documents have small square icons, folders have folder icons
5. Use nav_up/nav_down ONLY for scrolling when items are not visible
6. After clicking a document, wait for content to appear on the RIGHT panel

=== HOW TO IDENTIFY SUCCESS ===

You have SUCCEEDED (status="finished") when:
- You double-clicked on a document (date-named item, not a folder)
- The right pane now shows report content (text, patient info, medical notes)
- The document is from "History and Physical" (not "23 Hour...")
  OR from "ER/ED Notes" as fallback

=== LOOP PREVENTION ===

- Check RECENT HISTORY - if you just did an action and nothing changed, try different approach
- If a folder won't open after 2 attempts, try another folder
- If stuck in "23 Hour..." section, backtrack and try ER/ED Notes
- Don't keep clicking the same element repeatedly

=== OUTPUT FORMAT ===

- status="running" + action + target_id → Continue navigating
- status="finished" → Report is now visible, task complete
- status="error" → Cannot find any valid report after exhausting options
- target_id MUST match an ID from UI_ELEMENTS list - DO NOT invent IDs"""


USER_PROMPT = """Analyze this screenshot of the Jackson EMR Notes tree.

CURRENT UI_ELEMENTS:
{elements_text}

RECENT ACTION HISTORY:
{history}

Based on the current state, decide your next action to find and open the H&P report.
Remember: Avoid "23 Hour History and Physical Update Note" documents.
If you see report content on the right pane, you can finish."""


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
        self, elements_text: str = "", history: str = "", **kwargs
    ) -> str:
        return USER_PROMPT.format(
            elements_text=elements_text, history=history or "(none)"
        )

    def decide_action(
        self,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
        history: List[Dict[str, Any]] = None,
    ) -> ReportFinderResult:
        """
        Decide the next action based on current screen state.

        Args:
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser
            history: Recent action history for loop prevention

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
        )

        logger.info(
            f"[REPORT_FINDER] Action: {result.action}, Target: {result.target_id}, Status: {result.status}"
        )
        return result
