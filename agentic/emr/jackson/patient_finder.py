"""
PatientFinderAgent for Jackson EMR.
Finds a patient in the patient list and returns the element_id to click.
"""

from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agentic.core.base_agent import BaseAgent
from logger import logger


# =============================================================================
# PROMPTS - Edit these to optimize agent behavior
# =============================================================================

SYSTEM_PROMPT = """You are PatientFinderAgent for Jackson Hospital EMR.

TASK: Find the patient "{patient_name}" in the patient list visible on screen.

INSTRUCTIONS:
1. Analyze the screenshot and UI_ELEMENTS list
2. Look for an element that contains "{patient_name}"
3. Patient names appear as "LASTNAME, FIRSTNAME" format
4. Match should be case-insensitive

OUTPUT RULES:
- If you find the patient AND have its element_id: status="found", element_id=<ID>
- If you SEE the patient in the image but CANNOT find its ID in UI_ELEMENTS: status="retry"
  (This happens when OCR didn't detect the text properly - we'll retry with new capture)
- If patient is definitely NOT visible in the image: status="not_found"
- The element_id MUST be one of the IDs in UI_ELEMENTS - Do NOT invent IDs

WHEN TO USE "retry":
- You can clearly see the patient name in the screenshot
- But the UI_ELEMENTS list doesn't have a matching element
- This is an OCR failure, not a missing patient

CRITICAL: Jackson has only ONE patient tab. If the patient is not visible at all, return not_found immediately."""


USER_PROMPT = """Analyze this screenshot of the patient list.

UI_ELEMENTS:
{elements_text}

Find the patient and return the element_id to click.
If you see the patient but can't find the ID, return status="retry"."""


# =============================================================================
# AGENT
# =============================================================================


class PatientFinderResult(BaseModel):
    """Structured output for PatientFinderAgent."""

    status: Literal["found", "not_found", "retry"] = Field(
        description="'found' if patient located with ID, 'retry' if visible but ID missing, 'not_found' if not visible"
    )
    element_id: Optional[int] = Field(
        default=None,
        description="OmniParser element ID of the patient row. Only set if status='found'",
    )
    reasoning: str = Field(description="Brief explanation of the decision")


class PatientFinderAgent(BaseAgent):
    """
    Agent that finds a specific patient in Jackson's patient list.
    Returns the OmniParser element_id if found, or signals not_found/retry.
    """

    emr_type = "jackson"
    agent_name = "patient_finder"
    max_steps = 1
    temperature = 0.2

    def get_output_schema(self) -> Type[BaseModel]:
        return PatientFinderResult

    def get_system_prompt(self, patient_name: str = "", **kwargs) -> str:
        return SYSTEM_PROMPT.format(patient_name=patient_name)

    def get_user_prompt(self, elements_text: str = "", **kwargs) -> str:
        return USER_PROMPT.format(elements_text=elements_text)

    def find_patient(
        self,
        patient_name: str,
        image_base64: str,
        ui_elements: List[Dict[str, Any]],
    ) -> PatientFinderResult:
        """
        Find a patient in the visible list.

        Args:
            patient_name: Name of patient to find
            image_base64: Base64-encoded screenshot
            ui_elements: List of UI elements from OmniParser

        Returns:
            PatientFinderResult with status and element_id
        """
        logger.info(f"[PATIENT_FINDER] Looking for '{patient_name}'...")

        # Format elements before invoking
        elements_text = self.format_ui_elements(ui_elements)

        result = self.invoke(
            image_base64=image_base64,
            patient_name=patient_name,
            elements_text=elements_text,
        )

        logger.info(
            f"[PATIENT_FINDER] Result: {result.status}, ID: {result.element_id}"
        )
        return result
