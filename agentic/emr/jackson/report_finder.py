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

SYSTEM_PROMPT = """You are ReportFinderAgent for Jackson Hospital EMR.

TASK: Navigate the Notes tree to find a "History and Physical" report.

AVAILABLE ACTIONS:
- click: Single click on an element (use to focus/select)
- dblclick: Double click to open/expand folders or documents
- nav_up: Click the UP arrow to scroll document list up
- nav_down: Click the DOWN arrow to scroll document list down
- wait: Do nothing this step (use sparingly)

NAVIGATION STRATEGY:
1. Find "History and Physical Notes" folder → dblclick to open
2. Find "History and Physical" subfolder → dblclick to open
3. Find most recent document (look for dates MM/DD/YYYY) → dblclick to open
4. When report content is visible on right pane → status="finished"

TREE NAVIGATION RULES:
- ALWAYS double-click on folder TEXT, NOT on [+]/[-] icons
- If a folder is already expanded (shows subitems), look inside it
- Use nav_up/nav_down ONLY when you need to scroll to see more items

OUTPUT RULES:
- status="running" + action + target_id for navigation steps
- status="finished" when report content is visible
- target_id MUST be from UI_ELEMENTS list
- Do NOT invent IDs

LOOP PREVENTION:
- Check history - if you just did an action and UI didn't change, try different approach
- If folder won't open after 2 tries, try a different folder"""


USER_PROMPT = """Analyze this screenshot of the notes tree.

UI_ELEMENTS:
{elements_text}

RECENT HISTORY:
{history}

Decide the next action to navigate to the report."""


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
