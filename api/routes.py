"""
API Routes - FastAPI endpoint definitions.
"""

from fastapi import APIRouter, BackgroundTasks

from core.rpa_engine import rpa_state
from flows import BaptistFlow, JacksonFlow, JacksonSummaryFlow, StewardFlow

from .models import (
    StartRPARequest,
    StartSummaryRequest,
    StartRPAResponse,
    FlowStatusResponse,
)


router = APIRouter()


@router.get("/")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "RPA Agent is running"}


@router.get("/flow-status", response_model=FlowStatusResponse)
async def get_flow_status():
    """Get current RPA flow status."""
    return {
        "success": True,
        "message": "rpa flow status",
        "data": {
            "status": rpa_state["status"],
            "execution_id": rpa_state["execution_id"],
            "current_step": rpa_state["current_step"],
            "sender": rpa_state["sender"],
            "instance": rpa_state["instance"],
            "trigger_type": rpa_state["trigger_type"],
            "doctor_name": rpa_state.get("doctor_name"),
        },
    }


@router.post("/start-rpa-flow", response_model=StartRPAResponse)
async def start_rpa_flow(body: StartRPARequest, background_tasks: BackgroundTasks):
    """Start Baptist Health RPA flow (non-blocking)."""
    if rpa_state["status"] == "running":
        return {
            "success": False,
            "message": f"RPA is already running with ID: {rpa_state['execution_id']}",
        }

    print(f"Execution ID: {body.execution_id}")
    print(f"Sender: {body.sender}")
    print(f"Instance: {body.instance}")
    print(f"Trigger Type: {body.trigger_type}")
    print(f"Doctor Name: {body.doctor_name}")

    # Create and run flow in background
    flow = BaptistFlow()
    background_tasks.add_task(
        flow.run,
        body.execution_id,
        body.sender,
        body.instance,
        body.trigger_type,
        body.doctor_name,
        body.credentials,
    )

    return {
        "success": True,
        "message": "Baptist Health patient list capture started",
    }


@router.post("/start-jackson-rpa-flow", response_model=StartRPAResponse)
async def start_jackson_rpa_flow(
    body: StartRPARequest, background_tasks: BackgroundTasks
):
    """Start Jackson Health RPA flow (non-blocking)."""
    if rpa_state["status"] == "running":
        return {
            "success": False,
            "message": f"RPA is already running with ID: {rpa_state['execution_id']}",
        }

    print(f"Execution ID: {body.execution_id}")
    print(f"Sender: {body.sender}")
    print(f"Instance: {body.instance}")
    print(f"Trigger Type: {body.trigger_type} (Jackson)")
    print(f"Doctor Name: {body.doctor_name}")

    # Create and run flow in background
    flow = JacksonFlow()
    background_tasks.add_task(
        flow.run,
        body.execution_id,
        body.sender,
        body.instance,
        body.trigger_type,
        body.doctor_name,
        body.credentials,
    )

    return {
        "success": True,
        "message": "Jackson Health patient list capture started",
    }


@router.post("/start-steward-rpa-flow", response_model=StartRPAResponse)
async def start_steward_rpa_flow(
    body: StartRPARequest, background_tasks: BackgroundTasks
):
    """Start Steward RPA flow (non-blocking)."""
    if rpa_state["status"] == "running":
        return {
            "success": False,
            "message": f"RPA is already running with ID: {rpa_state['execution_id']}",
        }

    print(f"Execution ID: {body.execution_id}")
    print(f"Sender: {body.sender}")
    print(f"Instance: {body.instance}")
    print(f"Trigger Type: {body.trigger_type} (Steward)")
    print(f"Doctor Name: {body.doctor_name}")

    # Create and run flow in background
    flow = StewardFlow()
    background_tasks.add_task(
        flow.run,
        body.execution_id,
        body.sender,
        body.instance,
        body.trigger_type,
        body.doctor_name,
        body.credentials,
    )

    return {
        "success": True,
        "message": "Steward list recovery started",
    }


@router.post("/start-jackson-summary-flow", response_model=StartRPAResponse)
async def start_jackson_summary_flow(
    body: StartSummaryRequest, background_tasks: BackgroundTasks
):
    """
    Start Jackson Patient Summary flow - hybrid RPA + Agentic.

    This flow:
    1. Uses traditional RPA to navigate to the patient list
    2. Uses agentic brain to find the patient's Final Report
    3. Uses traditional RPA to copy content and close everything
    """
    if rpa_state["status"] == "running":
        return {
            "success": False,
            "message": f"RPA is already running with ID: {rpa_state['execution_id']}",
        }

    print(f"Execution ID: {body.execution_id}")
    print(f"Sender: {body.sender}")
    print(f"Instance: {body.instance}")
    print(f"Trigger Type: {body.trigger_type} (Jackson Summary)")
    print(f"Doctor Name: {body.doctor_name}")
    print(f"Patient Name: {body.patient_name}")

    # Create and run hybrid flow in background
    flow = JacksonSummaryFlow()
    background_tasks.add_task(
        flow.run,
        body.execution_id,
        body.sender,
        body.instance,
        body.trigger_type,
        body.doctor_name,
        body.credentials,
        body.patient_name,
    )

    return {
        "success": True,
        "message": f"Jackson patient summary flow started for patient: {body.patient_name}",
    }
