"""
Flows module - Hospital-specific RPA flows.
"""

from .base_flow import BaseFlow
from .baptist import BaptistFlow
from .jackson import JacksonFlow
from .steward import StewardFlow

# Flow registry for dynamic dispatch
FLOW_REGISTRY = {
    "baptist": BaptistFlow,
    "jackson": JacksonFlow,
    "steward": StewardFlow,
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
    "JacksonFlow",
    "StewardFlow",
    "FLOW_REGISTRY",
    "get_flow",
]
