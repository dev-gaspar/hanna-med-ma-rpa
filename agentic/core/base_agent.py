"""
Base Agent class for all EMR-specific agents.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from logger import logger
from .llm import create_vision_model


class BaseAgent(ABC):
    """
    Base class for vision-based agents.

    Subclasses must implement:
        - get_system_prompt(**context) -> str
        - get_user_prompt(**context) -> str
        - get_output_schema() -> Type[BaseModel]
    """

    emr_type: str = ""
    agent_name: str = ""
    max_steps: int = 5
    temperature: float = 0.2

    def __init__(self):
        self.model: Optional[ChatGoogleGenerativeAI] = None

    def _ensure_model(self) -> ChatGoogleGenerativeAI:
        """Lazy-load the model on first use."""
        if self.model is None:
            self.model = create_vision_model(temperature=self.temperature)
        return self.model

    @abstractmethod
    def get_system_prompt(self, **context) -> str:
        """Return the system prompt for this agent."""
        pass

    @abstractmethod
    def get_user_prompt(self, **context) -> str:
        """Return the user prompt for this agent."""
        pass

    @abstractmethod
    def get_output_schema(self) -> Type[BaseModel]:
        """Return the Pydantic model for structured output."""
        pass

    def invoke(self, image_base64: Optional[str] = None, **context) -> BaseModel:
        """
        Invoke the agent with current screen state.

        Args:
            image_base64: Optional base64-encoded screenshot
            **context: All context passed directly to get_system_prompt() and get_user_prompt()

        Returns:
            Structured output as defined by get_output_schema()
        """
        model = self._ensure_model()

        # Get prompts from subclass - pass all context directly
        system_prompt = self.get_system_prompt(**context)
        user_prompt = self.get_user_prompt(**context)
        output_schema = self.get_output_schema()

        # Create structured model using json_schema method (recommended for v4.0+)
        # See: https://docs.langchain.com/integrations/chat/google_generative_ai
        structured_model = model.with_structured_output(
            schema=output_schema, method="json_schema"
        )

        # Build user message content
        user_content = []

        # Add image if provided
        if image_base64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                }
            )

        # Add text prompt with timestamp prefix
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_prompt_with_timestamp = f"CURRENT DATE/TIME: {timestamp}\n\n{user_prompt}"
        user_content.append({"type": "text", "text": user_prompt_with_timestamp})

        # Build messages
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        logger.info(f"[{self.agent_name.upper()}] Invoking Gemini...")

        # Retry logic for when structured output returns None
        max_retries = 3
        result = None

        for attempt in range(max_retries):
            try:
                result = structured_model.invoke(messages)

                if result is not None:
                    logger.info(f"[{self.agent_name.upper()}] Response: {result}")
                    return result
                else:
                    logger.warning(
                        f"[{self.agent_name.upper()}] Received None response (attempt {attempt + 1}/{max_retries})"
                    )

            except Exception as e:
                logger.error(
                    f"[{self.agent_name.upper()}] Error on attempt {attempt + 1}: {e}"
                )
                if attempt == max_retries - 1:
                    raise

        # If we exhausted retries with None, raise an error
        raise ValueError(
            f"[{self.agent_name.upper()}] Failed to get structured response after {max_retries} attempts"
        )

    @staticmethod
    def format_ui_elements(elements: List[Dict[str, Any]]) -> str:
        """
        Utility to format UI elements for prompts.
        Call this in your agent before invoking if needed.
        """
        if not elements:
            return "(No elements detected)"

        lines = []
        for el in elements:
            el_id = el.get("id", "?")
            el_type = el.get("type", "unknown")
            content = el.get("content", "")[:120]
            center = el.get("center", [0, 0])
            lines.append(
                f"[{el_id}] ({el_type}) '{content}' at ({center[0]}, {center[1]})"
            )

        return "\n".join(lines)

    @staticmethod
    def format_history(
        history: List[Dict[str, Any]],
        max_entries: int = 10,
        reasoning_length: int = 100,
    ) -> str:
        """
        Format action history for prompts.

        Args:
            history: List of history entries with step, action, reasoning
            max_entries: Maximum number of entries to include
            reasoning_length: Max chars for reasoning truncation

        Returns:
            Formatted string for prompt inclusion
        """
        if not history:
            return "(No previous actions)"

        recent = history[-max_entries:]
        lines = []
        for h in recent:
            step = h.get("step", "?")
            action = h.get("action", "?")
            reasoning = h.get("reasoning", "")[:reasoning_length]
            lines.append(f"- Step {step}: {action} → {reasoning}")

        return "\n".join(lines)

    @staticmethod
    def detect_loop(
        history: List[Dict[str, Any]],
        consecutive_threshold: int = 3,
        alternating_check: bool = True,
    ) -> Tuple[bool, str]:
        """
        Detect navigation loops in action history.

        Args:
            history: List of history entries
            consecutive_threshold: How many same actions trigger warning
            alternating_check: Whether to check for alternating patterns

        Returns:
            Tuple of (is_loop_detected, warning_message)
        """
        if not history or len(history) < consecutive_threshold:
            return False, ""

        # Get recent actions
        recent_actions = [h.get("action", "") for h in history[-5:]]

        # Check consecutive same actions
        if len(recent_actions) >= consecutive_threshold:
            last_action = recent_actions[-1]
            consecutive = sum(1 for a in reversed(recent_actions) if a == last_action)

            if consecutive >= consecutive_threshold:
                return True, (
                    f"⚠️ WARNING: '{last_action}' repeated {consecutive} times! "
                    "You may be stuck. Consider: CLOSE folder (dblclick) and try NEXT PRIORITY."
                )

        # Check alternating pattern (nav_up, nav_down, nav_up, nav_down)
        if alternating_check and len(recent_actions) >= 4:
            nav_actions = ("nav_up", "nav_down")
            alternating = all(
                recent_actions[i] != recent_actions[i + 1]
                and recent_actions[i] in nav_actions
                and recent_actions[i + 1] in nav_actions
                for i in range(len(recent_actions) - 1)
            )
            if alternating:
                return True, (
                    "⚠️ WARNING: Alternating nav_up/nav_down detected! "
                    "You are STUCK. CLOSE this folder (dblclick) and move to NEXT PRIORITY folder."
                )

        # Check repeated reasoning patterns
        recent_reasonings = [h.get("reasoning", "")[:50] for h in history[-4:]]
        if (
            len(recent_reasonings) >= 3
            and len(set(recent_reasonings)) == 1
            and recent_reasonings[0]  # Not empty
        ):
            return True, (
                "⚠️ WARNING: Same action pattern repeated! "
                "Try a different approach or move to next priority."
            )

        return False, ""
