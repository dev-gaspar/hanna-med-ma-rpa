"""
Authentication Service - Login and credential management.
"""

import requests
from typing import Optional, Dict, Any

from config import config
from logger import logger


class AuthService:
    """Handles authentication with the backend."""

    def __init__(self):
        self.backend_url = config.BACKEND_URL

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        Authenticate a doctor with the backend.

        Args:
            username: Doctor's username
            password: Doctor's password

        Returns:
            Dict with 'success' boolean and either 'doctor' data or 'error' message
        """
        try:
            response = requests.post(
                f"{self.backend_url}/auth/doctor-login",
                json={"username": username, "password": password},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                doctor = data.get("doctor")
                if doctor:
                    # Store password temporarily for tunnel config
                    doctor["_password"] = password
                    return {"success": True, "doctor": doctor}
                else:
                    return {"success": False, "error": "Invalid response from server"}
            else:
                error_msg = response.json().get("message", "Invalid credentials")
                return {"success": False, "error": error_msg}

        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to server")
            return {"success": False, "error": "Cannot connect to server"}
        except requests.exceptions.Timeout:
            logger.error("Connection timeout")
            return {"success": False, "error": "Connection timeout"}
        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return {"success": False, "error": f"Error: {str(e)}"}

    def fetch_tunnel_config(self, username: str, password: str) -> Dict[str, Any]:
        """
        Fetch tunnel configuration from backend.

        Args:
            username: Doctor's username
            password: Doctor's password

        Returns:
            Dict with tunnel configuration or error
        """
        try:
            logger.info(f"Fetching tunnel config for {username}")

            response = requests.post(
                f"{self.backend_url}/doctors/rpa-config",
                json={"username": username, "password": password},
                timeout=30,
            )

            if response.status_code not in [200, 201]:
                logger.error(f"Bad response status: {response.status_code}")
                return {
                    "success": False,
                    "error": f"Failed to fetch tunnel config (Status: {response.status_code})",
                }

            data = response.json()

            if not data.get("success"):
                logger.error("Invalid credentials")
                return {"success": False, "error": "Invalid credentials"}

            tunnel_info = data.get("tunnel", {})
            tunnel_id = tunnel_info.get("tunnelId")
            tunnel_name = tunnel_info.get("tunnelName")
            credentials = tunnel_info.get("credentials")
            config_data = tunnel_info.get("config")

            logger.info(f"Tunnel: {tunnel_name} (ID: {tunnel_id})")

            return {
                "success": True,
                "tunnel_id": tunnel_id,
                "tunnel_name": tunnel_name,
                "credentials": credentials,
                "config": config_data,
            }

        except Exception as e:
            logger.error(f"Exception in fetch_tunnel_config: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}
