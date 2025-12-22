"""
Pydantic models for the Agentic RPA module.
Defines all data structures used across the agent system.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
import uuid


class ActionType(str, Enum):
    """Supported agent actions."""

    # Mouse actions
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    DRAG = "drag"  # Drag from one point to another

    # Keyboard actions
    TYPE = "type"
    KEY_PRESS = "key_press"  # Press a single key (enter, escape, tab, etc.)
    HOTKEY = "hotkey"  # Keyboard shortcut (ctrl+c, ctrl+v, alt+tab, etc.)

    # Navigation actions
    SCROLL = "scroll"

    # Control actions
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    FINISH = "finish"


class AgentStatus(str, Enum):
    """Agent execution status."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    STOPPED = "stopped"
    PATIENT_NOT_FOUND = "patient_not_found"


class UIElement(BaseModel):
    """
    A UI element detected by OmniParser.

    Attributes:
        id: Unique identifier for this element in the current screen
        type: Element type (text, icon, button, etc.)
        content: Text content or description
        bbox: Bounding box [x1, y1, x2, y2] in pixels
        center: Center point (x, y) for click targeting
        confidence: Detection confidence score
    """

    id: int
    type: str
    content: str = ""
    bbox: List[float] = Field(default_factory=list)
    center: Tuple[int, int] = (0, 0)
    confidence: float = 0.0
    interactable: bool = True

    def __str__(self) -> str:
        return f"ID {self.id}: [{self.type}] '{self.content}' at {self.center}"


class ParsedScreen(BaseModel):
    """
    Result of OmniParser analysis.

    Attributes:
        elements: List of detected UI elements
        screen_size: Screen dimensions (width, height)
        timestamp: When the screen was captured
        raw_response: Raw OmniParser response for debugging
    """

    elements: List[UIElement] = Field(default_factory=list)
    screen_size: Tuple[int, int] = (0, 0)
    timestamp: datetime = Field(default_factory=datetime.now)
    raw_response: Optional[str] = None
    labeled_image_url: Optional[str] = None

    def get_element_by_id(self, element_id: int) -> Optional[UIElement]:
        """Find element by ID."""
        for element in self.elements:
            if element.id == element_id:
                return element
        return None

    def find_elements_by_content(
        self, text: str, case_sensitive: bool = False
    ) -> List[UIElement]:
        """Find elements containing specific text."""
        results = []
        search_text = text if case_sensitive else text.lower()
        for element in self.elements:
            content = element.content if case_sensitive else element.content.lower()
            if search_text in content:
                results.append(element)
        return results

    def to_simplified_list(self) -> str:
        """Convert elements to simplified string for LLM context."""
        lines = []
        for element in self.elements:
            lines.append(f"ID {element.id}: [{element.type}] '{element.content}'")
        return "\n".join(lines)


class AgentAction(BaseModel):
    """
    An action to be executed by the agent.

    Attributes:
        action: Type of action to perform
        target_id: UI element ID to interact with (from ParsedScreen)
        coords: Explicit coordinates (x, y) if not using target_id
        text: Text to type (for TYPE action)
        direction: Scroll direction (for SCROLL action)
        reasoning: LLM's explanation for this action
    """

    action: ActionType
    target_id: Optional[int] = None
    coords: Optional[Tuple[int, int]] = None
    end_coords: Optional[Tuple[int, int]] = None  # For drag action (end position)
    text: Optional[str] = None
    key: Optional[str] = (
        None  # For key_press: enter, escape, tab, up, down, left, right, etc.
    )
    keys: Optional[List[str]] = None  # For hotkey: ["ctrl", "c"], ["alt", "tab"], etc.
    direction: Optional[Literal["up", "down", "left", "right"]] = "down"
    scroll_amount: Optional[int] = None  # Custom scroll amount (pixels)
    reasoning: str = ""


class AgentStep(BaseModel):
    """
    A single step in the agent's history.

    Attributes:
        step_number: Sequential step number
        action: The action that was executed
        reasoning: Why this action was chosen
        success: Whether the action succeeded
        error: Error message if failed
        timestamp: When the step was executed
    """

    step_number: int
    action: ActionType
    target_id: Optional[int] = None
    reasoning: str = ""
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_history_string(self) -> str:
        """Convert to string for LLM context."""
        status = "✓" if self.success else "✗"
        return f"Step {self.step_number} [{status}]: {self.action.value} - {self.reasoning}"


class AgentRequest(BaseModel):
    """
    Request payload sent to n8n brain webhook.

    Attributes:
        execution_id: Unique ID for this execution
        goal: The objective to achieve
        step_number: Current step count
        history: Previous steps taken
        screen: Current parsed screen state
        screenshot_url: Optional S3 URL of screenshot for debugging
    """

    execution_id: str
    goal: str
    step_number: int
    history: List[Dict[str, Any]] = Field(default_factory=list)
    screen: Dict[str, Any] = Field(default_factory=dict)
    screenshot_url: Optional[str] = None


class AgentResponse(BaseModel):
    """
    Response from n8n brain webhook.

    Attributes:
        action: Action to execute (used for single action mode)
        target_id: Element ID to interact with
        coords: Explicit coordinates (overrides target_id)
        text: Text for type action
        direction: Scroll direction
        reasoning: Explanation of the decision
        status: Current status (running/finished/error)
        output: Final output when status is finished
        batch: List of actions for batch/burst mode (VDI optimization)
    """

    action: ActionType = ActionType.WAIT  # Default for batch mode
    target_id: Optional[int] = None
    coords: Optional[Tuple[int, int]] = None
    end_coords: Optional[Tuple[int, int]] = None  # For drag action
    text: Optional[str] = None
    key: Optional[str] = None  # For key_press action
    keys: Optional[List[str]] = None  # For hotkey action
    direction: Optional[str] = None
    scroll_amount: Optional[int] = None  # Custom scroll amount
    reasoning: str = ""
    status: AgentStatus = AgentStatus.RUNNING
    output: Optional[Any] = None
    batch: Optional[List[Dict[str, Any]]] = None  # Batch mode: list of actions


class AgentResult(BaseModel):
    """
    Final result of an agent execution.

    Attributes:
        execution_id: Unique execution ID
        goal: The original goal
        status: Final status
        output: Final output/result
        steps_taken: Number of steps executed
        history: Full history of steps
        error: Error message if failed
        started_at: Execution start time
        finished_at: Execution end time
    """

    execution_id: str
    goal: str
    status: AgentStatus
    output: Optional[str] = None
    steps_taken: int = 0
    history: List[AgentStep] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None


class AgenticTaskRequest(BaseModel):
    """
    Request to start an agentic task via API.

    Attributes:
        goal: The objective to achieve
        max_steps: Maximum steps before timeout
        step_delay: Delay between steps in seconds
        upload_screenshots: Whether to upload screenshots to S3
        callback_url: Optional URL to POST final result
    """

    goal: str
    max_steps: int = 500
    step_delay: float = 1.0
    upload_screenshots: bool = True
    callback_url: Optional[str] = None


class AgenticState(BaseModel):
    """
    Current state of the agentic runner (for status endpoint).

    Attributes:
        status: Current status
        execution_id: Current execution ID
        goal: Current goal
        current_step: Current step number
        last_action: Last action taken
        last_reasoning: Reasoning for last action
    """

    status: AgentStatus = AgentStatus.IDLE
    execution_id: Optional[str] = None
    goal: Optional[str] = None
    current_step: int = 0
    last_action: Optional[str] = None
    last_reasoning: Optional[str] = None
