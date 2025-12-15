"""
API Models - Pydantic request/response models.
"""

from pydantic import BaseModel


class StartRPARequest(BaseModel):
    """Request model for starting an RPA flow."""

    execution_id: str
    sender: str
    instance: str
    trigger_type: str


class StartRPAResponse(BaseModel):
    """Response model for RPA start endpoints."""

    success: bool
    message: str


class FlowStatusResponse(BaseModel):
    """Response model for flow status endpoint."""

    success: bool
    message: str
    data: dict
