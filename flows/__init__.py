"""
Flows module - Hospital-specific RPA flows.
"""

from .base_flow import BaseFlow
from .baptist import BaptistFlow
from .baptist_summary import BaptistSummaryFlow
from .baptist_insurance import BaptistInsuranceFlow
from .baptist_batch_insurance import BaptistBatchInsuranceFlow
from .jackson import JacksonFlow
from .jackson_summary import JacksonSummaryFlow
from .steward import StewardFlow
from .steward_summary import StewardSummaryFlow

# Batch summary flows
from .base_batch_summary import BaseBatchSummaryFlow
from .batch_summary_registry import (
    get_batch_summary_flow,
    get_available_hospitals,
    is_hospital_supported,
)
from .jackson_batch_summary import JacksonBatchSummaryFlow
from .baptist_batch_summary import BaptistBatchSummaryFlow
from .steward_batch_summary import StewardBatchSummaryFlow

# Flow registry for dynamic dispatch
FLOW_REGISTRY = {
    "baptist": BaptistFlow,
    "baptist_summary": BaptistSummaryFlow,
    "baptist_insurance": BaptistInsuranceFlow,
    "baptist_batch_insurance": BaptistBatchInsuranceFlow,
    "jackson": JacksonFlow,
    "jackson_summary": JacksonSummaryFlow,
    "steward": StewardFlow,
    "steward_summary": StewardSummaryFlow,
    # Batch summaries
    "jackson_batch_summary": JacksonBatchSummaryFlow,
    "baptist_batch_summary": BaptistBatchSummaryFlow,
    "steward_batch_summary": StewardBatchSummaryFlow,
}


def get_flow(flow_name: str) -> BaseFlow:
    """
    Get a flow instance by name.

    Args:
        flow_name: Name of the flow (baptist, jackson, steward)

    Returns:
        Instance of the corresponding flow class

    Raises:
        ValueError: If flow name is not recognized
    """
    flow_class = FLOW_REGISTRY.get(flow_name.lower())
    if flow_class is None:
        raise ValueError(
            f"Unknown flow: {flow_name}. Available flows: {list(FLOW_REGISTRY.keys())}"
        )
    return flow_class()


__all__ = [
    "BaseFlow",
    "BaptistFlow",
    "BaptistSummaryFlow",
    "BaptistInsuranceFlow",
    "BaptistBatchInsuranceFlow",
    "JacksonFlow",
    "JacksonSummaryFlow",
    "StewardFlow",
    "StewardSummaryFlow",
    "BaseBatchSummaryFlow",
    "JacksonBatchSummaryFlow",
    "BaptistBatchSummaryFlow",
    "StewardBatchSummaryFlow",
    "FLOW_REGISTRY",
    "get_flow",
    "get_batch_summary_flow",
    "get_available_hospitals",
    "is_hospital_supported",
]
