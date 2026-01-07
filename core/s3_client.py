"""
S3 Client - AWS S3 operations for RPA.
Handles screenshot uploads, PDF uploads, and presigned URL generation.
"""

import base64
import os
from datetime import datetime
from io import BytesIO
from typing import List, Optional

import boto3
import pyautogui

from config import config


class S3Client:
    """AWS S3 client for RPA file operations."""

    def __init__(self):
        self.access_key = config.get_rpa_setting("aws.access_key_id")
        self.secret_key = config.get_rpa_setting("aws.secret_access_key")
        self.bucket_name = config.get_rpa_setting("aws.bucket_name")
        self.region = config.get_rpa_setting("aws.region")
        self.s3_prefix = config.get_rpa_setting("aws.s3_prefix", "baptist-health")
        self._client = None

    def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            if not self.access_key or not self.secret_key:
                raise Exception("AWS credentials not configured")
            if not self.bucket_name:
                raise Exception("AWS S3 bucket name not configured")
            if not self.region:
                raise Exception("AWS region not configured")

            self._client = boto3.client(
                "s3",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    def take_screenshot(self):
        """Takes a screenshot and returns it as bytes."""
        screenshot = pyautogui.screenshot()
        img_buffer = BytesIO()
        screenshot.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        return img_buffer

    def upload_image(self, img_buffer, filename):
        """Upload an image to S3."""
        print(f"[S3] Uploading: {filename}")

        try:
            client = self._get_client()
            client.upload_fileobj(
                img_buffer,
                self.bucket_name,
                filename,
                ExtraArgs={"ContentType": "image/png"},
            )
            print(f"[S3] Upload successful")
            return filename
        except Exception as e:
            print(f"[S3] Upload failed: {str(e)}")
            raise Exception(f"Failed to upload to S3: {str(e)}")

    def upload_pdf(self, file_path, s3_filename):
        """Upload a PDF file to S3."""
        print(f"[S3] Uploading PDF: {s3_filename}")

        try:
            client = self._get_client()
            with open(file_path, "rb") as f:
                client.upload_fileobj(
                    f,
                    self.bucket_name,
                    s3_filename,
                    ExtraArgs={"ContentType": "application/pdf"},
                )
            print("[S3] PDF upload successful")
            return s3_filename
        except Exception as e:
            print(f"[S3] PDF upload failed: {str(e)}")
            raise Exception(f"Failed to upload PDF to S3: {str(e)}")

    def generate_presigned_url(self, filename, expiration=86400):
        """Generate a presigned URL (expires in 24 hours by default)."""
        client = self._get_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": filename},
            ExpiresIn=expiration,
        )
        return url

    def capture_screenshot_for_hospital(
        self, hospital_full_name, display_name, hospital_index, execution_id
    ):
        """Capture screenshot of a specific hospital."""
        print(f"[SCREENSHOT] Capturing {display_name} - {hospital_full_name}")

        if not self.s3_prefix:
            raise Exception("AWS S3 prefix not configured")

        img_buffer = self.take_screenshot()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.s3_prefix}/{execution_id}/patient-list_{display_name}_{timestamp}.png"
        self.upload_image(img_buffer, filename)
        image_url = self.generate_presigned_url(filename)

        return {
            "hospital_name": hospital_full_name,
            "display_name": display_name,
            "hospital_index": hospital_index,
            "screenshot_url": image_url,
            "timestamp": timestamp,
            "filename": filename,
        }

    def capture_screenshot_with_processing(
        self,
        hospital_full_name: str,
        display_name: str,
        hospital_index: int,
        execution_id: str,
        rois: Optional[List] = None,
        enhance: bool = False,
    ) -> dict:
        """
        Capture screenshot with optional ROI masking and VDI enhancement.

        Args:
            hospital_full_name: Full name of the hospital
            display_name: Display name for the screenshot
            hospital_index: Index of the hospital
            execution_id: Unique execution ID
            rois: List of ROI objects for masking (from agentic.models)
            enhance: Whether to apply VDI enhancement (upscale, contrast, sharpness)

        Returns:
            Dict with screenshot metadata and presigned URL
        """
        from agentic.screen_capturer import ScreenCapturer

        print(
            f"[SCREENSHOT] Capturing {display_name} - {hospital_full_name} (processed)"
        )

        if not self.s3_prefix:
            raise Exception("AWS S3 prefix not configured")

        capturer = ScreenCapturer()

        if rois:
            if enhance:
                # Apply ROI mask + VDI enhancement (upscale 2x, contrast, sharpness)
                image_b64 = capturer.capture_with_mask_enhanced_base64(
                    rois,
                    enhance=True,
                    upscale_factor=2.0,
                    contrast_factor=1.3,
                    sharpness_factor=1.5,
                )
                print(
                    f"[SCREENSHOT] Applied ROI mask ({len(rois)} regions) + VDI enhancement"
                )
            else:
                # Apply ROI mask only
                image_b64 = capturer.capture_with_mask_base64(rois)
                print(f"[SCREENSHOT] Applied ROI mask ({len(rois)} regions)")

            # Convert base64 to BytesIO for upload
            img_data = base64.b64decode(image_b64)
            img_buffer = BytesIO(img_data)
        else:
            # No processing, use standard screenshot
            img_buffer = self.take_screenshot()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.s3_prefix}/{execution_id}/patient-list_{display_name}_{timestamp}.png"
        self.upload_image(img_buffer, filename)
        image_url = self.generate_presigned_url(filename)

        return {
            "hospital_name": hospital_full_name,
            "display_name": display_name,
            "hospital_index": hospital_index,
            "screenshot_url": image_url,
            "timestamp": timestamp,
            "filename": filename,
        }


# Singleton instance for convenience
_s3_client = None


def get_s3_client():
    """Get singleton S3 client instance."""
    global _s3_client
    if _s3_client is None:
        _s3_client = S3Client()
    return _s3_client
