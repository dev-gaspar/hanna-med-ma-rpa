"""
Action Executor - Executes agent actions on the screen.
Provides stoppable actions with logging and error handling.
"""

import time
from typing import Optional, Tuple

import pyautogui
import pydirectinput

from core.rpa_engine import check_should_stop, stoppable_sleep
from core.vdi_input import type_with_clipboard, press_key_vdi
from logger import logger

from .models import ActionType, AgentAction, ParsedScreen


class ActionExecutor:
    """
    Executes agent actions on the screen.
    All actions are stoppable and logged.

    Supports both single actions and batch execution for VDI optimization.
    """

    # Pause between actions in a batch (for VDI/Citrix environments)
    BATCH_PAUSE = 0.5

    def __init__(
        self,
        click_duration: float = 0.3,
        type_delay: float = 0.05,
        action_delay: float = 0.5,
    ):
        """
        Initialize the action executor.

        Args:
            click_duration: Duration for mouse movement animation
            type_delay: Delay between keystrokes
            action_delay: Delay after each action
        """
        self.click_duration = click_duration
        self.type_delay = type_delay
        self.action_delay = action_delay

    def execute_batch(
        self,
        actions: list,
        parsed_screen: Optional[ParsedScreen] = None,
    ) -> Tuple[bool, int]:
        """
        Execute a batch of actions sequentially (Burst Mode for VDI optimization).

        Args:
            actions: List of action dicts from n8n batch response
            parsed_screen: Current parsed screen for resolving target_id

        Returns:
            Tuple of (all_succeeded, actions_executed_count)
        """
        from .models import AgentAction, ActionType

        logger.info(f"[ACTION] ⚡ Executing BATCH of {len(actions)} actions")

        executed_count = 0

        for i, action_data in enumerate(actions):
            check_should_stop()

            # Parse action from dict
            action_str = action_data.get("action", "wait")
            try:
                action_type = ActionType(action_str)
            except ValueError:
                logger.warning(f"[ACTION] Unknown action in batch: {action_str}")
                continue

            # Build AgentAction from dict
            action = AgentAction(
                action=action_type,
                target_id=action_data.get("target_id"),
                coords=(
                    tuple(action_data["coords"]) if action_data.get("coords") else None
                ),
                end_coords=(
                    tuple(action_data["end_coords"])
                    if action_data.get("end_coords")
                    else None
                ),
                text=action_data.get("text"),
                key=action_data.get("key"),
                keys=action_data.get("keys"),
                direction=action_data.get("direction"),
                scroll_amount=action_data.get("scroll_amount"),
                reasoning=action_data.get("reasoning", f"Batch step {i+1}"),
            )

            logger.info(f"[ACTION] Batch [{i+1}/{len(actions)}]: {action_type.value}")

            # Execute single action
            success = self.execute(action, parsed_screen)

            if not success:
                logger.warning(f"[ACTION] ❌ Batch action {i+1} failed, stopping batch")
                return False, executed_count

            executed_count += 1

            # Tactical pause between batch actions (crucial for VDI)
            if i < len(actions) - 1:  # Don't pause after last action
                stoppable_sleep(self.BATCH_PAUSE)

        logger.info(
            f"[ACTION] ✓ Batch complete: {executed_count}/{len(actions)} actions executed"
        )
        return True, executed_count

    def execute(
        self,
        action: AgentAction,
        parsed_screen: Optional[ParsedScreen] = None,
    ) -> bool:
        """
        Execute an agent action.

        Args:
            action: The action to execute
            parsed_screen: Current parsed screen (for resolving target_id to coords)

        Returns:
            True if action succeeded, False otherwise
        """
        check_should_stop()

        # Resolve coordinates from target_id if needed
        coords = action.coords
        if coords is None and action.target_id is not None and parsed_screen:
            element = parsed_screen.get_element_by_id(action.target_id)
            if element:
                coords = element.center
                logger.info(
                    f"[ACTION] Resolved ID {action.target_id} to coords {coords}"
                )
            else:
                logger.warning(
                    f"[ACTION] Could not find element with ID {action.target_id}"
                )
                return False

        # Execute based on action type
        try:
            if action.action == ActionType.CLICK:
                return self._execute_click(coords, action.reasoning)

            elif action.action == ActionType.DOUBLE_CLICK:
                return self._execute_double_click(coords, action.reasoning)

            elif action.action == ActionType.TYPE:
                return self._execute_type(action.text, action.reasoning)

            elif action.action == ActionType.SCROLL:
                return self._execute_scroll(
                    action.direction, action.reasoning, coords, action.scroll_amount
                )

            elif action.action == ActionType.WAIT:
                return self._execute_wait(action.reasoning)

            elif action.action == ActionType.SCREENSHOT:
                # Screenshot is handled by the runner, not executor
                logger.info(f"[ACTION] Screenshot requested: {action.reasoning}")
                return True

            elif action.action == ActionType.FINISH:
                logger.info(f"[ACTION] Finish: {action.reasoning}")
                return True

            elif action.action == ActionType.KEY_PRESS:
                return self._execute_key_press(action.key, action.reasoning)

            elif action.action == ActionType.HOTKEY:
                return self._execute_hotkey(action.keys, action.reasoning)

            elif action.action == ActionType.DRAG:
                return self._execute_drag(coords, action.end_coords, action.reasoning)

            else:
                logger.warning(f"[ACTION] Unknown action type: {action.action}")
                return False

        except Exception as e:
            logger.error(f"[ACTION] Error executing {action.action}: {e}")
            return False

    def _execute_click(self, coords: Optional[Tuple[int, int]], reasoning: str) -> bool:
        """Execute a single click."""
        if coords is None:
            logger.warning("[ACTION] Click requires coordinates")
            return False

        x, y = coords
        logger.info(f"[ACTION] Click at ({x}, {y}): {reasoning}")

        # Move smoothly then click
        pyautogui.moveTo(x, y, duration=self.click_duration)
        stoppable_sleep(0.1)
        pyautogui.click()

        stoppable_sleep(self.action_delay)
        return True

    def _execute_double_click(
        self, coords: Optional[Tuple[int, int]], reasoning: str
    ) -> bool:
        """Execute a double click."""
        if coords is None:
            logger.warning("[ACTION] Double click requires coordinates")
            return False

        x, y = coords
        logger.info(f"[ACTION] Double-click at ({x}, {y}): {reasoning}")

        # Move smoothly then double click
        pyautogui.moveTo(x, y, duration=self.click_duration)
        stoppable_sleep(0.1)
        pyautogui.doubleClick()

        stoppable_sleep(self.action_delay)
        return True

    def _execute_type(self, text: Optional[str], reasoning: str) -> bool:
        """Execute typing text."""
        if not text:
            logger.warning("[ACTION] Type requires text")
            return False

        logger.info(f"[ACTION] Type '{text[:30]}...': {reasoning}")

        # Use clipboard method for VDI compatibility
        type_with_clipboard(text)

        stoppable_sleep(self.action_delay)
        return True

    def _execute_scroll(
        self,
        direction: Optional[str],
        reasoning: str,
        coords: Optional[Tuple[int, int]] = None,
        scroll_amount: Optional[int] = None,
    ) -> bool:
        """Execute scroll action at specific coordinates or center of screen."""
        # Get target position
        if coords:
            x, y = coords
        else:
            # If no coords, scroll at center-right of screen (main content area typically)
            screen_width, screen_height = pyautogui.size()
            x = int(screen_width * 0.65)  # 65% from left (main content area)
            y = int(screen_height * 0.5)  # Center vertically

        # Move mouse to scroll position and click to focus
        logger.info(f"[ACTION] Moving to ({x}, {y}) for scroll")
        pyautogui.moveTo(x, y, duration=0.2)
        stoppable_sleep(0.1)
        pyautogui.click()  # Click to ensure focus
        stoppable_sleep(0.2)

        # Determine scroll amount (positive = up, negative = down)
        if scroll_amount is not None:
            amount = scroll_amount
        else:
            amount = 500 if direction == "up" else -500

        logger.info(f"[ACTION] Scroll {direction or 'down'} ({amount}px): {reasoning}")
        pyautogui.scroll(amount)

        stoppable_sleep(self.action_delay)
        return True

    def _execute_wait(self, reasoning: str) -> bool:
        """Execute wait action."""
        logger.info(f"[ACTION] Wait: {reasoning}")
        stoppable_sleep(2.0)
        return True

    def _execute_key_press(self, key: Optional[str], reasoning: str) -> bool:
        """Execute a single key press (enter, escape, tab, arrows, etc.)."""
        if not key:
            logger.warning("[ACTION] Key press requires a key")
            return False

        # Map common key names
        key_map = {
            "enter": "return",
            "esc": "escape",
            "del": "delete",
            "backspace": "backspace",
            "tab": "tab",
            "space": "space",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "home": "home",
            "end": "end",
            "pageup": "pageup",
            "pagedown": "pagedown",
            "escape": "escape",
            "return": "return",
            # Windows key
            "win": "win",
            "windows": "win",
            "winleft": "winleft",
            "winright": "winright",
            # Function keys
            "f1": "f1",
            "f2": "f2",
            "f3": "f3",
            "f4": "f4",
            "f5": "f5",
            "f6": "f6",
            "f7": "f7",
            "f8": "f8",
            "f9": "f9",
            "f10": "f10",
            "f11": "f11",
            "f12": "f12",
        }

        actual_key = key_map.get(key.lower(), key.lower())
        logger.info(f"[ACTION] Key press '{actual_key}': {reasoning}")

        # Use pyautogui for Win key and other special keys (pydirectinput doesn't handle win key well)
        # pyautogui uses 'win' while pydirectinput may not support it
        special_keys = {"win", "winleft", "winright"}

        try:
            if actual_key in special_keys:
                # Use pyautogui for windows key - it handles it properly
                pyautogui.press(actual_key)
            else:
                # Try pydirectinput first for VDI compatibility
                pydirectinput.press(actual_key)
        except Exception as e:
            logger.warning(
                f"[ACTION] Key press failed with first method: {e}, trying pyautogui fallback"
            )
            try:
                pyautogui.press(actual_key)
            except Exception as e2:
                logger.error(f"[ACTION] Both key press methods failed: {e2}")
                return False

        stoppable_sleep(self.action_delay)
        return True

    def _execute_hotkey(self, keys: Optional[list], reasoning: str) -> bool:
        """Execute a keyboard shortcut (e.g., ctrl+c, alt+tab)."""
        if not keys or len(keys) < 2:
            logger.warning("[ACTION] Hotkey requires at least 2 keys")
            return False

        logger.info(f"[ACTION] Hotkey {'+'.join(keys)}: {reasoning}")

        # pyautogui.hotkey accepts multiple args
        pyautogui.hotkey(*keys)
        stoppable_sleep(self.action_delay)
        return True

    def _execute_drag(
        self,
        start_coords: Optional[Tuple[int, int]],
        end_coords: Optional[Tuple[int, int]],
        reasoning: str,
    ) -> bool:
        """Execute a drag action from start to end coordinates."""
        if not start_coords or not end_coords:
            logger.warning("[ACTION] Drag requires both start and end coordinates")
            return False

        start_x, start_y = start_coords
        end_x, end_y = end_coords

        logger.info(
            f"[ACTION] Drag from ({start_x}, {start_y}) to ({end_x}, {end_y}): {reasoning}"
        )

        # Move to start, press, drag to end, release
        pyautogui.moveTo(start_x, start_y, duration=self.click_duration)
        stoppable_sleep(0.1)
        pyautogui.mouseDown()
        stoppable_sleep(0.1)
        pyautogui.moveTo(end_x, end_y, duration=self.click_duration * 2)
        stoppable_sleep(0.1)
        pyautogui.mouseUp()

        stoppable_sleep(self.action_delay)
        return True

    def click_at(self, x: int, y: int, description: str = "element") -> bool:
        """
        Convenience method for clicking at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            description: Description for logging
        """
        action = AgentAction(
            action=ActionType.CLICK,
            coords=(x, y),
            reasoning=f"Click on {description}",
        )
        return self.execute(action)

    def type_text(self, text: str) -> bool:
        """
        Convenience method for typing text.

        Args:
            text: Text to type
        """
        action = AgentAction(
            action=ActionType.TYPE,
            text=text,
            reasoning=f"Type text",
        )
        return self.execute(action)

    def scroll_down(self) -> bool:
        """Convenience method for scrolling down."""
        action = AgentAction(
            action=ActionType.SCROLL,
            direction="down",
            reasoning="Scroll down",
        )
        return self.execute(action)

    def scroll_up(self) -> bool:
        """Convenience method for scrolling up."""
        action = AgentAction(
            action=ActionType.SCROLL,
            direction="up",
            reasoning="Scroll up",
        )
        return self.execute(action)


# Singleton instance
_executor_instance: Optional[ActionExecutor] = None


def get_action_executor() -> ActionExecutor:
    """Get or create the singleton action executor."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = ActionExecutor()
    return _executor_instance
