"""
Agentic RPA Module - Autonomous agent with OmniParser vision and LLM decision-making.

This module provides an autonomous agent that can navigate UIs by:
1. Capturing screenshots
2. Analyzing them with OmniParser (via Replicate API)
3. Sending context to n8n for LLM decision-making
4. Executing actions (click, type, scroll, etc.)

Example usage:
    from agentic import AgentRunner, OmniParserClient

    runner = AgentRunner(
        n8n_webhook_url="https://n8n.example.com/webhook/agentic-brain"
    )
    result = runner.run(goal="Read the last message from Juan in WhatsApp Web")
"""

from .models import (
    UIElement,
    ParsedScreen,
    AgentAction,
    AgentStep,
    AgentRequest,
    AgentResponse,
    AgentResult,
    AgenticTaskRequest,
    AgenticState,
)
from .omniparser_client import OmniParserClient
from .screen_capturer import ScreenCapturer
from .action_executor import ActionExecutor
from .agent_runner import AgentRunner

__all__ = [
    # Models
    "UIElement",
    "ParsedScreen",
    "AgentAction",
    "AgentStep",
    "AgentRequest",
    "AgentResponse",
    "AgentResult",
    "AgenticTaskRequest",
    "AgenticState",
    # Clients
    "OmniParserClient",
    "ScreenCapturer",
    "ActionExecutor",
    "AgentRunner",
]
