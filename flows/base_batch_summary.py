"""
Base Batch Summary Flow - Abstract base class for batch patient summary flows.

This module provides the extensible architecture for batch summary operations.
New EMRs can be added by:
1. Creating a new class inheriting from BaseBatchSummaryFlow
2. Implementing the abstract methods
3. Registering in batch_summary_registry.py
"""

import time
from abc import ABC, abstractmethod
from typing import List, Optional

from .base_flow import BaseFlow
from logger import logger


class BaseBatchSummaryFlow(BaseFlow, ABC):
    """
    Abstract base class for batch patient summary flows.

    Provides template method pattern for processing multiple patients
    while keeping the EMR session open.
    """

    FLOW_TYPE = "batch_summary"

    def __init__(self):
        super().__init__()
        self.patient_names: List[str] = []
        self.hospital_type: str = ""
        self.current_patient: Optional[str] = None
        self.current_content: Optional[str] = None
        self.results: List[dict] = []

    def setup(
        self,
        execution_id,
        sender,
        instance,
        trigger_type,
        doctor_name=None,
        credentials=None,
        patient_names=None,
        hospital_type=None,
        **kwargs,
    ):
        """Setup flow with execution context."""
        super().setup(
            execution_id,
            sender,
            instance,
            trigger_type,
            doctor_name,
            credentials,
            **kwargs,
        )
        self.patient_names = patient_names or []
        self.hospital_type = hospital_type or self.FLOW_NAME
        self.results = []
        logger.info(
            f"[BATCH-SUMMARY] Setup for {len(self.patient_names)} patients in {self.hospital_type}"
        )

    def execute(self):
        """
        Template method - executes the batch summary flow.

        1. Navigate to patient list (once)
        2. For each patient: find, extract content
        3. Cleanup (once)
        4. Return consolidated results
        """
        logger.info(f"[BATCH-SUMMARY] Starting batch for {self.patient_names}")

        # Phase 1: Navigate to patient list (once)
        if not self.navigate_to_patient_list():
            logger.error("[BATCH-SUMMARY] Failed to navigate to patient list")
            return {
                "patients": [],
                "hospital": self.hospital_type,
                "error": "Navigation failed",
            }

        # Phase 2: Process each patient without closing EMR
        for patient in self.patient_names:
            self.current_patient = patient
            self.current_content = None
            logger.info(f"[BATCH-SUMMARY] Processing patient: {patient}")

            try:
                found = self.find_patient(patient)
                if found:
                    self.current_content = self.extract_content()
                    logger.info(f"[BATCH-SUMMARY] Extracted content for {patient}")
                    # ALWAYS close patient detail view after extraction
                    # This returns us to the patient list for next search or cleanup
                    self.return_to_patient_list()
                else:
                    logger.warning(f"[BATCH-SUMMARY] Patient not found: {patient}")

                self.results.append(
                    {
                        "patient": patient,
                        "found": found,
                        "content": self.current_content,
                    }
                )

            except Exception as e:
                logger.error(f"[BATCH-SUMMARY] Error processing {patient}: {str(e)}")
                self.results.append(
                    {
                        "patient": patient,
                        "found": False,
                        "content": None,
                        "error": str(e),
                    }
                )

        # Phase 3: Cleanup
        logger.info("[BATCH-SUMMARY] Cleanup phase")
        self.cleanup()

        return {
            "patients": self.results,
            "hospital": self.hospital_type,
            "total": len(self.patient_names),
            "found_count": sum(1 for r in self.results if r.get("found")),
        }

    @abstractmethod
    def navigate_to_patient_list(self) -> bool:
        """
        Navigate to the patient list in the EMR.
        Called once at the beginning.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def find_patient(self, patient_name: str) -> bool:
        """
        Search for a patient by name in the current view.

        Args:
            patient_name: Name of the patient to find.

        Returns:
            True if patient found and report opened, False otherwise.
        """
        pass

    @abstractmethod
    def extract_content(self) -> str:
        """
        Extract the clinical content from the current patient view.

        Returns:
            Extracted content as string.
        """
        pass

    @abstractmethod
    def return_to_patient_list(self):
        """
        Return to the patient list view after extracting content.
        Called between patients (not after the last one).
        """
        pass

    @abstractmethod
    def cleanup(self):
        """
        Close EMR session and return to lobby.
        Called once at the end.
        """
        pass

    def notify_completion(self, result):
        """Send consolidated results to n8n webhook."""
        import requests
        from config import config

        webhook_url = config.get_rpa_setting("n8n_batch_summary_webhook_url")

        payload = {
            "status": "completed",
            "type": f"batch_{self.hospital_type.lower()}_summary",
            "execution_id": self.execution_id,
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
            "hospital": self.hospital_type,
            "patients": result.get("patients", []),
            "total": result.get("total", 0),
            "found_count": result.get("found_count", 0),
        }

        logger.info(f"[BATCH-SUMMARY] Sending results to webhook: {webhook_url}")
        try:
            response = requests.post(webhook_url, json=payload, timeout=30)
            logger.info(f"[BATCH-SUMMARY] Webhook response: {response.status_code}")
        except Exception as e:
            logger.error(f"[BATCH-SUMMARY] Webhook error: {str(e)}")
