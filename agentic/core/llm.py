"""
LLM module - Gemini model factory for agentic architecture.
"""

from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from config import config
from logger import logger


def get_gemini_api_key() -> str:
    """Get Gemini API key from rpa_config.json."""
    api_key = config.get_rpa_setting("agentic.google_api_key")
    if api_key:
        return api_key

    raise ValueError(
        "Google API key not found. Add 'agentic.google_api_key' to rpa_config.json"
    )


def create_gemini_model(
    model_name: str = "gemini-3-flash-preview",
    temperature: float = 0.2,
    max_retries: int = 2,
) -> ChatGoogleGenerativeAI:
    """
    Create a ChatGoogleGenerativeAI model instance.

    Args:
        model_name: Gemini model to use
        temperature: Sampling temperature
        max_retries: Number of retries on API errors

    Returns:
        Configured ChatGoogleGenerativeAI instance
    """
    api_key = get_gemini_api_key()

    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_retries=max_retries,
    )

    logger.info(f"[LLM] Created Gemini model: {model_name}")
    return model


def create_vision_model(
    model_name: str = "gemini-3-flash-preview",
    temperature: float = 0.2,
) -> ChatGoogleGenerativeAI:
    """Create a Gemini model for vision tasks."""
    return create_gemini_model(model_name=model_name, temperature=temperature)
