"""
Batch Summary Registry - Factory for batch summary flows.

This module provides the extensible registry pattern for batch summary flows.
To add a new EMR:
1. Create a new class inheriting from BaseBatchSummaryFlow
2. Add an entry to BATCH_SUMMARY_FLOWS with the hospital key and class path
"""

import importlib
from typing import TYPE_CHECKING

from logger import logger

if TYPE_CHECKING:
    from .base_batch_summary import BaseBatchSummaryFlow


# Registry of available batch summary flows
# Format: "HOSPITAL_KEY": "module.path.ClassName"
BATCH_SUMMARY_FLOWS = {
    "JACKSON": "flows.jackson_batch_summary.JacksonBatchSummaryFlow",
    "BAPTIST": "flows.baptist_batch_summary.BaptistBatchSummaryFlow",
    "STEWARD": "flows.steward_batch_summary.StewardBatchSummaryFlow",
}


def get_batch_summary_flow(hospital_type: str) -> "BaseBatchSummaryFlow":
    """
    Factory function to get a batch summary flow for a hospital.

    Args:
        hospital_type: Hospital key (e.g., "JACKSON", "BAPTIST")

    Returns:
        Instance of the appropriate batch summary flow.

    Raises:
        ValueError: If hospital_type is not supported.
    """
    hospital_key = hospital_type.upper()
    flow_path = BATCH_SUMMARY_FLOWS.get(hospital_key)

    if not flow_path:
        available = list(BATCH_SUMMARY_FLOWS.keys())
        raise ValueError(
            f"No batch summary flow for: {hospital_key}. " f"Available: {available}"
        )

    # Dynamic import
    module_path, class_name = flow_path.rsplit(".", 1)
    logger.info(f"[REGISTRY] Loading flow: {class_name} from {module_path}")

    try:
        module = importlib.import_module(module_path)
        flow_class = getattr(module, class_name)
        logger.info(f"[REGISTRY] Instantiating {class_name}...")
        flow_instance = flow_class()
        logger.info(f"[REGISTRY] Successfully instantiated {class_name}")
        return flow_instance
    except (ImportError, AttributeError) as e:
        logger.error(f"[REGISTRY] Failed to load flow: {e}")
        raise ValueError(f"Failed to load flow for {hospital_key}: {e}")
    except Exception as e:
        logger.error(f"[REGISTRY] Unexpected error instantiating flow: {e}")
        raise


def get_available_hospitals() -> list:
    """Get list of hospitals with batch summary support."""
    return list(BATCH_SUMMARY_FLOWS.keys())


def is_hospital_supported(hospital_type: str) -> bool:
    """Check if a hospital has batch summary support."""
    return hospital_type.upper() in BATCH_SUMMARY_FLOWS
