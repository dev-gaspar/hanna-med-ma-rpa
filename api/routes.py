"""
API Routes - FastAPI endpoint definitions.
"""

from fastapi import APIRouter, BackgroundTasks

from core.rpa_engine import (
    rpa_state,
    enqueue_request,
    dequeue_request,
    get_queue_status,
)
from flows import (
    BaptistFlow,
    BaptistSummaryFlow,
    JacksonFlow,
    JacksonSummaryFlow,
    StewardFlow,
)

from .models import (
    StartRPARequest,
    StartSummaryRequest,
    StartRPAResponse,
    FlowStatusResponse,
    QueueRPARequest,
    QueueRPAResponse,
    QueueStatusResponse,
    HospitalType,
)

from logger import logger


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
        patient_name=body.patient_name,
    )

    return {
        "success": True,
        "message": f"Jackson patient summary flow started for patient: {body.patient_name}",
    }


@router.post("/start-baptist-summary-flow", response_model=StartRPAResponse)
async def start_baptist_summary_flow(
    body: StartSummaryRequest, background_tasks: BackgroundTasks
):
    """
    Start Baptist Patient Summary flow - hybrid RPA + Agentic.

    This flow:
    1. Uses traditional RPA to navigate to the patient list
    2. Uses agentic brain to find the patient across hospital tabs
    3. Uses traditional RPA to close and cleanup
    """
    if rpa_state["status"] == "running":
        return {
            "success": False,
            "message": f"RPA is already running with ID: {rpa_state['execution_id']}",
        }

    print(f"Execution ID: {body.execution_id}")
    print(f"Sender: {body.sender}")
    print(f"Instance: {body.instance}")
    print(f"Trigger Type: {body.trigger_type} (Baptist Summary)")
    print(f"Doctor Name: {body.doctor_name}")
    print(f"Patient Name: {body.patient_name}")

    # Create and run hybrid flow in background
    flow = BaptistSummaryFlow()
    background_tasks.add_task(
        flow.run,
        body.execution_id,
        body.sender,
        body.instance,
        body.trigger_type,
        body.doctor_name,
        body.credentials,
        patient_name=body.patient_name,
    )

    return {
        "success": True,
        "message": f"Baptist patient summary flow started for patient: {body.patient_name}",
    }


# ============================================================================
# Queue Endpoints for Batch Processing
# ============================================================================


def get_flow_for_hospital(hospital_type: str):
    """Get the appropriate flow class for a hospital type."""
    flows_map = {
        "JACKSON": JacksonFlow,
        "STEWARD": StewardFlow,
        "BAPTIST": BaptistFlow,
    }
    flow_class = flows_map.get(hospital_type.upper())
    if not flow_class:
        raise ValueError(f"Unknown hospital type: {hospital_type}")
    return flow_class()


def process_queue():
    """
    Process queued requests sequentially.
    This function runs in a background task and processes each request one by one.
    """
    import time

    logger.info("[QUEUE] Starting queue processor")

    while True:
        request = dequeue_request()
        if not request:
            logger.info("[QUEUE] No more requests, queue empty")
            break

        hospital_type = request.get("hospital_type", "UNKNOWN")
        logger.info(f"[QUEUE] Processing next: {hospital_type}")

        try:
            flow = get_flow_for_hospital(hospital_type)
            flow.run(
                request["execution_id"],
                request["sender"],
                request["instance"],
                request["trigger_type"],
                request["doctor_name"],
                request.get("credentials"),
            )
        except Exception as e:
            logger.error(f"[QUEUE] Error processing {hospital_type}: {str(e)}")

        # Small pause between flows to let the VDI stabilize
        time.sleep(2)

    logger.info("[QUEUE] Queue processor finished")


@router.post("/queue-rpa-flow", response_model=QueueRPAResponse)
async def queue_rpa_flow(body: QueueRPARequest, background_tasks: BackgroundTasks):
    """
    Queue an RPA flow for execution.

    This endpoint adds the request to a queue and processes it when the RPA is available.
    Used for batch operations where multiple hospitals need to be processed sequentially.
    """
    request_data = {
        "hospital_type": body.hospital_type.value,
        "execution_id": body.execution_id,
        "sender": body.sender,
        "instance": body.instance,
        "trigger_type": body.trigger_type,
        "doctor_name": body.doctor_name,
        "credentials": body.credentials,
        "batch_id": body.batch_id,
    }

    position = enqueue_request(request_data)
    logger.info(
        f"[QUEUE] Request queued: {body.hospital_type.value} at position {position}"
    )

    # If RPA is idle, start processing the queue
    if rpa_state["status"] == "idle":
        logger.info("[QUEUE] RPA is idle, starting queue processor")
        background_tasks.add_task(process_queue)

    return {
        "success": True,
        "message": f"Request for {body.hospital_type.value} queued at position {position}",
        "queue_position": position,
    }


@router.get("/queue-status", response_model=QueueStatusResponse)
async def get_queue_status_endpoint():
    """Get the current status of the request queue."""
    status = get_queue_status()
    return status
