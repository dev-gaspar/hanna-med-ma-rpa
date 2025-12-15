"""
Logging system for RPA Agent
"""

import logging
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime


def setup_logger(name: str = "RPA") -> logging.Logger:
    """Setup logger with file and console handlers"""

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Setup file logging
    try:
        from config import config

        logs_dir = config.get_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = logs_dir / f"rpa_{timestamp}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        logger.info("=" * 60)
        logger.info(f"RPA Agent Log Started - {datetime.now()}")
        logger.info(f"Log file: {log_file}")
        logger.info(f"Backend URL: {config.BACKEND_URL}")
        logger.info("=" * 60)

    except Exception as e:
        # Fallback to temp directory
        try:
            temp_dir = Path(tempfile.gettempdir()) / "HannaMedRPA"
            temp_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = temp_dir / f"rpa_{timestamp}.log"

            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

            logger.warning(f"Using temporary log file: {log_file}")
            logger.error(f"Failed to create log in AppData: {e}")

        except Exception as e2:
            logger.warning("Running without file logging - console only")

    return logger


# Create default logger
logger = setup_logger()
