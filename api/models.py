"""
API Models - Pydantic request/response models.
"""

from typing import Optional, List
from pydantic import BaseModel
from enum import Enum


class SystemKey(str, Enum):
    """EMR system keys."""

    JACKSON = "JACKSON"
    STEWARD = "STEWARD"


class CredentialItem(BaseModel):
    """Credential for a specific EMR system."""

    systemKey: SystemKey
    fields: dict  # {"username": "...", "password": "..."} or {"email": "...", "password": "..."}


class StartRPARequest(BaseModel):
    """Request model for starting an RPA flow."""

    execution_id: str
    sender: str
    instance: str
    trigger_type: str
    doctor_name: Optional[str] = None
    credentials: Optional[List[CredentialItem]] = (
        None  # Array of credentials per system
    )


class StartSummaryRequest(StartRPARequest):
    """Request model for starting a patient summary flow."""

    patient_name: str  # Name of the patient to find


class StartRPAResponse(BaseModel):
    """Response model for RPA start endpoints."""

    success: bool
    message: str


class FlowStatusResponse(BaseModel):
    """Response model for flow status endpoint."""

    success: bool
    message: str
    data: dict


class AgenticTaskResponse(BaseModel):
    """Response model for agentic task endpoints."""

    success: bool
    message: str
    execution_id: Optional[str] = None
    data: Optional[dict] = None
