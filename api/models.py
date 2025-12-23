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


class HospitalType(str, Enum):
    """Hospital type for queue requests."""

    JACKSON = "JACKSON"
    STEWARD = "STEWARD"
    BAPTIST = "BAPTIST"


class QueueRPARequest(BaseModel):
    """Request model for queueing an RPA flow."""

    execution_id: str
    sender: str
    instance: str
    trigger_type: str
    doctor_name: Optional[str] = None
    hospital_type: HospitalType  # Required: which hospital to run
    credentials: Optional[List[CredentialItem]] = None
    batch_id: Optional[str] = None  # To group batch requests together


class QueueRPAResponse(BaseModel):
    """Response model for queue endpoints."""

    success: bool
    message: str
    queue_position: Optional[int] = None


class QueueStatusResponse(BaseModel):
    """Response model for queue status endpoint."""

    pending: int
    current_status: str
    queue: List[str]
