"""
Agent Runner - Main orchestrator for the agentic RPA.
Runs the perception-decision-action loop with memory.
"""

import base64
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from config import config
from core.rpa_engine import check_should_stop, set_should_stop, stoppable_sleep
from core.s3_client import get_s3_client
from logger import logger

from .models import (
    ActionType,
    AgentAction,
    AgentResponse,
    AgentResult,
    AgentStatus,
    AgentStep,
    AgenticState,
    ParsedScreen,
)
from .omniparser_client import OmniParserClient, get_omniparser_client
from .screen_capturer import ScreenCapturer, get_screen_capturer
from .action_executor import ActionExecutor, get_action_executor


# Global state for the agentic runner
_agentic_state = AgenticState()


def get_agentic_state() -> AgenticState:
    """Get the current agentic runner state."""
    return _agentic_state


class AgentRunner:
    """
    Main orchestrator for the agentic RPA.

    Runs a perception-decision-action loop:
    1. Capture screen
    2. Parse with OmniParser
    3. Send to n8n brain for decision
    4. Execute action
    5. Update history
    6. Repeat until finished or max steps
    """

    def __init__(
        self,
        n8n_webhook_url: Optional[str] = None,
        omniparser_client: Optional[OmniParserClient] = None,
        screen_capturer: Optional[ScreenCapturer] = None,
        action_executor: Optional[ActionExecutor] = None,
        max_steps: int = 50,
        step_delay: float = 2.0,
        request_timeout: float = 120.0,
        upload_screenshots: bool = True,
    ):
        """
        Initialize the agent runner.

        Args:
            n8n_webhook_url: URL of the n8n brain webhook
            omniparser_client: OmniParser client instance
            screen_capturer: Screen capturer instance
            action_executor: Action executor instance
            max_steps: Maximum steps before timeout
            step_delay: Delay between steps in seconds
            request_timeout: Timeout for n8n requests
            upload_screenshots: Whether to upload screenshots to S3 for debugging
        """
        # Get n8n URL from config if not provided
        self.n8n_webhook_url = n8n_webhook_url or config.get_rpa_setting(
            "agentic.n8n_agentic_webhook_url"
        )

        if not self.n8n_webhook_url:
            raise ValueError(
                "n8n webhook URL not provided. Set in config or pass to constructor."
            )

        # Use provided instances or get singletons
        self.omniparser = omniparser_client or get_omniparser_client()
        self.capturer = screen_capturer or get_screen_capturer()
        self.executor = action_executor or get_action_executor()

        # Settings
        self.max_steps = max_steps or config.get_rpa_setting("agentic.max_steps", 50)
        self.step_delay = step_delay or config.get_rpa_setting(
            "agentic.step_delay_seconds", 2.0
        )
        self.request_timeout = request_timeout or config.get_rpa_setting(
            "agentic.request_timeout_seconds", 120.0
        )
        self.upload_screenshots = upload_screenshots

        # S3 client for screenshot uploads
        self.s3_client = get_s3_client() if upload_screenshots else None

        # Execution state
        self.execution_id: Optional[str] = None
        self.goal: Optional[str] = None
        self.history: List[AgentStep] = []
        self.current_step: int = 0

        logger.info(
            f"[AGENT] Runner initialized with webhook: {self.n8n_webhook_url[:50]}..."
        )

    def run(self, goal: str, callback_url: Optional[str] = None) -> AgentResult:
        """
        Run the agent to achieve a goal.

        Args:
            goal: The objective to achieve
            callback_url: Optional URL to POST final result

        Returns:
            AgentResult with outcome and history
        """
        global _agentic_state

        # Initialize execution
        self.execution_id = str(uuid.uuid4())[:8]
        self.goal = goal
        self.history = []
        self.current_step = 0

        started_at = datetime.now()

        # Update global state
        _agentic_state = AgenticState(
            status=AgentStatus.RUNNING,
            execution_id=self.execution_id,
            goal=goal,
            current_step=0,
        )

        logger.info("=" * 70)
        logger.info(f" AGENTIC RPA - STARTING")
        logger.info("=" * 70)
        logger.info(f"[AGENT] Execution ID: {self.execution_id}")
        logger.info(f"[AGENT] Goal: {goal}")
        logger.info(f"[AGENT] Max steps: {self.max_steps}")
        logger.info("=" * 70)

        result = AgentResult(
            execution_id=self.execution_id,
            goal=goal,
            status=AgentStatus.RUNNING,
            started_at=started_at,
        )

        try:
            # Main loop
            while self.current_step < self.max_steps:
                check_should_stop()

                self.current_step += 1
                logger.info(
                    f"\n[AGENT] === Step {self.current_step}/{self.max_steps} ==="
                )

                # Update state
                _agentic_state.current_step = self.current_step

                # 1. Capture screen
                logger.info("[AGENT] Capturing screen...")
                data_url = self.capturer.capture_data_url()

                # 2. Parse with OmniParser
                logger.info("[AGENT] Analyzing with OmniParser...")
                parsed_screen = self.omniparser.parse_image(data_url)
                logger.info(
                    f"[AGENT] Detected {len(parsed_screen.elements)} UI elements"
                )

                # 3. Upload screenshot if enabled
                screenshot_url = None
                if self.upload_screenshots and self.s3_client:
                    try:
                        screenshot_url = self._upload_screenshot(data_url)
                    except Exception as e:
                        logger.warning(f"[AGENT] Failed to upload screenshot: {e}")

                # 4. Send to n8n brain
                logger.info("[AGENT] Consulting brain (n8n)...")
                response = self._consult_brain(parsed_screen, screenshot_url)

                if response is None:
                    logger.error("[AGENT] Brain returned no response, stopping")
                    result.status = AgentStatus.ERROR
                    result.error = "No response from n8n brain"
                    break

                logger.info(f"[AGENT] Brain decided: {response.action.value}")
                logger.info(f"[AGENT] Reasoning: {response.reasoning}")

                # Update state
                _agentic_state.last_action = response.action.value
                _agentic_state.last_reasoning = response.reasoning

                # 5. Check if finished
                if response.status == AgentStatus.FINISHED:
                    logger.info("[AGENT] Brain signaled FINISHED")
                    result.status = AgentStatus.FINISHED
                    result.output = response.output

                    # Record final step
                    step = AgentStep(
                        step_number=self.current_step,
                        action=response.action,
                        target_id=response.target_id,
                        reasoning=response.reasoning,
                        success=True,
                    )
                    self.history.append(step)
                    break

                # 6. Execute action(s) - BATCH MODE or SINGLE MODE
                if (
                    response.batch
                    and isinstance(response.batch, list)
                    and len(response.batch) > 0
                ):
                    # BATCH MODE: Execute multiple actions in sequence
                    logger.info(f"[AGENT] ⚡ BATCH MODE: {len(response.batch)} actions")
                    success, executed_count = self.executor.execute_batch(
                        response.batch, parsed_screen
                    )

                    # Record batch as single step
                    step = AgentStep(
                        step_number=self.current_step,
                        action=ActionType.CLICK,  # Representative action for batch
                        target_id=(
                            response.batch[0].get("target_id")
                            if response.batch
                            else None
                        ),
                        reasoning=f"[BATCH x{executed_count}] {response.reasoning}",
                        success=success,
                    )
                else:
                    # SINGLE MODE: Execute one action
                    action = AgentAction(
                        action=response.action,
                        target_id=response.target_id,
                        coords=response.coords,
                        end_coords=response.end_coords,
                        text=response.text,
                        key=response.key,
                        keys=response.keys,
                        direction=response.direction,
                        scroll_amount=response.scroll_amount,
                        reasoning=response.reasoning,
                    )

                    success = self.executor.execute(action, parsed_screen)

                    # Record step
                    step = AgentStep(
                        step_number=self.current_step,
                        action=response.action,
                        target_id=response.target_id,
                        reasoning=response.reasoning,
                        success=success,
                    )

                self.history.append(step)

                # 8. Delay before next step
                logger.info(f"[AGENT] Waiting {self.step_delay}s before next step...")
                stoppable_sleep(self.step_delay)

            else:
                # Max steps reached
                logger.warning("[AGENT] Max steps reached")
                result.status = AgentStatus.ERROR
                result.error = (
                    f"Max steps ({self.max_steps}) reached without completing goal"
                )

        except KeyboardInterrupt:
            logger.info("[AGENT] Stopped by user")
            result.status = AgentStatus.STOPPED
            result.error = "Stopped by user"

        except Exception as e:
            logger.error(f"[AGENT] Error: {e}", exc_info=True)
            result.status = AgentStatus.ERROR
            result.error = str(e)

        finally:
            # Finalize result
            result.finished_at = datetime.now()
            result.steps_taken = self.current_step
            result.history = self.history

            # Update global state
            _agentic_state = AgenticState(
                status=result.status,
                execution_id=self.execution_id,
                goal=goal,
                current_step=self.current_step,
                last_action=_agentic_state.last_action,
                last_reasoning=_agentic_state.last_reasoning,
            )

            logger.info("=" * 70)
            logger.info(f" AGENTIC RPA - {result.status.value.upper()}")
            logger.info(
                f" Steps: {result.steps_taken}, Output: {result.output or 'N/A'}"
            )
            logger.info("=" * 70)

            # Callback if provided
            if callback_url:
                self._send_callback(callback_url, result)

        return result

    def _consult_brain(
        self,
        parsed_screen: ParsedScreen,
        screenshot_url: Optional[str] = None,
    ) -> Optional[AgentResponse]:
        """
        Send current state to n8n brain and get action decision.

        Args:
            parsed_screen: Current parsed screen
            screenshot_url: Optional S3 URL of screenshot

        Returns:
            AgentResponse with action to execute
        """
        # Build request payload
        history_dicts = [
            {
                "step": step.step_number,
                "action": step.action.value,
                "reasoning": step.reasoning,
                "success": step.success,
            }
            for step in self.history[-10:]
        ]

        screen_dict = {
            "elements": [
                {
                    "id": el.id,
                    "type": el.type,
                    "content": el.content,
                    "center": list(el.center),
                    "bbox": el.bbox,
                }
                for el in parsed_screen.elements
            ],
            "element_count": len(parsed_screen.elements),
            "screen_size": list(parsed_screen.screen_size),
            "labeled_image": parsed_screen.labeled_image_url,  # Image with bounding boxes from OmniParser
        }

        payload = {
            "execution_id": self.execution_id,
            "goal": self.goal,
            "step_number": self.current_step,
            "history": history_dicts,
            "screen": screen_dict,
            "screenshot_url": screenshot_url,
        }

        try:
            response = requests.post(
                self.n8n_webhook_url,
                json=payload,
                timeout=self.request_timeout,
            )

            if response.status_code not in [200, 201]:
                logger.error(f"[AGENT] Brain returned status {response.status_code}")
                logger.error(f"[AGENT] Response body: {response.text[:500]}")
                return None

            # Log raw response for debugging
            raw_text = response.text
            if not raw_text or raw_text.strip() == "":
                logger.error("[AGENT] Brain returned empty response!")
                return None

            logger.debug(f"[AGENT] Raw brain response: {raw_text[:200]}...")

            data = response.json()

            # Check if response is wrapped in "output" key (n8n structured output)
            if "output" in data and isinstance(data["output"], dict):
                data = data["output"]

            # Parse batch if present (Burst Mode)
            batch = data.get("batch")
            if batch and isinstance(batch, list):
                logger.info(f"[AGENT] Received BATCH with {len(batch)} actions")

            # Parse response - for batch mode, action may be empty/wait
            action_str = data.get("action", "wait")
            try:
                action_type = ActionType(action_str)
            except ValueError:
                logger.warning(
                    f"[AGENT] Unknown action '{action_str}', defaulting to wait"
                )
                action_type = ActionType.WAIT

            status_str = data.get("status", "running")
            try:
                status = AgentStatus(status_str)
            except ValueError:
                status = AgentStatus.RUNNING

            # Map 'thought' to 'reasoning' for n8n compatibility
            reasoning = data.get("reasoning") or data.get("thought", "")

            return AgentResponse(
                action=action_type,
                target_id=data.get("target_id"),
                coords=tuple(data["coords"]) if data.get("coords") else None,
                end_coords=(
                    tuple(data["end_coords"]) if data.get("end_coords") else None
                ),
                text=data.get("text"),
                key=data.get("key"),
                keys=data.get("keys"),
                direction=data.get("direction"),
                scroll_amount=data.get("scroll_amount"),
                reasoning=reasoning,
                status=status,
                output=data.get("output"),
                batch=batch,
            )

        except requests.RequestException as e:
            logger.error(f"[AGENT] Request to brain failed: {e}")
            return None
        except Exception as e:
            logger.error(f"[AGENT] Error parsing brain response: {e}")
            # Log the raw response if available
            if "raw_text" in locals():
                logger.error(f"[AGENT] Raw response was: {raw_text[:300]}")
            return None

    def _upload_screenshot(self, data_url: str) -> Optional[str]:
        """Upload screenshot to S3 for debugging."""
        # Extract base64 data from data URL
        if "," in data_url:
            b64_data = data_url.split(",", 1)[1]
        else:
            b64_data = data_url

        # Convert to bytes
        img_bytes = base64.b64decode(b64_data)

        # Upload to S3
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"agentic/{self.execution_id}/step_{self.current_step}_{timestamp}.png"
        )

        from io import BytesIO

        img_buffer = BytesIO(img_bytes)

        self.s3_client.upload_image(img_buffer, filename)
        url = self.s3_client.generate_presigned_url(filename)

        logger.debug(f"[AGENT] Screenshot uploaded: {filename}")
        return url

    def _send_callback(self, callback_url: str, result: AgentResult) -> None:
        """Send final result to callback URL."""
        try:
            payload = {
                "execution_id": result.execution_id,
                "goal": result.goal,
                "status": result.status.value,
                "output": result.output,
                "steps_taken": result.steps_taken,
                "error": result.error,
                "history": [
                    {
                        "step": step.step_number,
                        "action": step.action.value,
                        "reasoning": step.reasoning,
                    }
                    for step in result.history
                ],
            }

            requests.post(callback_url, json=payload, timeout=10)
            logger.info(f"[AGENT] Callback sent to {callback_url}")

        except Exception as e:
            logger.warning(f"[AGENT] Failed to send callback: {e}")


def stop_agentic_runner() -> bool:
    """Stop the currently running agentic task."""
    global _agentic_state

    if _agentic_state.status != AgentStatus.RUNNING:
        return False

    set_should_stop(True)
    _agentic_state.status = AgentStatus.STOPPED
    logger.info("[AGENT] Stop requested")
    return True
