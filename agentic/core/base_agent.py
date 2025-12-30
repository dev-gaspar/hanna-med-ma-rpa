"""
Base Agent class for all EMR-specific agents.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

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

        # Create structured model
        structured_model = model.with_structured_output(
            schema=output_schema, method="function_calling"
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
        result = structured_model.invoke(messages)
        logger.info(f"[{self.agent_name.upper()}] Response: {result}")

        return result

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
            content = el.get("content", "")[:80]
            center = el.get("center", [0, 0])
            lines.append(f"[{el_id}] '{content}' at ({center[0]}, {center[1]})")

        return "\n".join(lines)
