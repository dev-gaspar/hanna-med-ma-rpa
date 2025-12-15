"""
Agent Service - RPA Agent lifecycle management.
"""

import socket
import threading
import time
from typing import Optional, Callable

import requests
import uvicorn

from config import config
from logger import logger
from tunnel_manager import TunnelManager


class AgentService:
    """Manages the RPA agent lifecycle including server and tunnel."""

    def __init__(self):
        self.tunnel_manager = TunnelManager()
        self.running = False
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.should_heartbeat = False

    def start_server(self, on_error: Optional[Callable[[str], None]] = None):
        """
        Start the FastAPI server in a background thread.

        Args:
            on_error: Optional callback for error handling
        """

        def run_server():
            try:
                from api import app

                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=8000,
                    log_config=None,
                    access_log=False,
                )
            except Exception as e:
                logger.error(f"Failed to start FastAPI server: {e}", exc_info=True)
                if on_error:
                    on_error(str(e))

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        logger.info("FastAPI server thread started")

    def wait_for_server(self, max_attempts: int = 10, delay: float = 1) -> bool:
        """
        Wait for the server to be ready.

        Args:
            max_attempts: Maximum number of connection attempts
            delay: Delay between attempts in seconds

        Returns:
            True if server is ready, False otherwise
        """
        for attempt in range(max_attempts):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", 8000))
                sock.close()

                if result == 0:
                    logger.info("FastAPI server is ready")
                    return True
                else:
                    time.sleep(delay)
            except Exception as e:
                logger.warning(f"Error checking server: {e}")
                time.sleep(delay)

        logger.error("FastAPI server failed to start")
        return False

    def start_tunnel(
        self,
        tunnel_id: str,
        tunnel_name: str,
        credentials: str,
        config_data: str,
    ) -> bool:
        """
        Start the Cloudflare tunnel.

        Args:
            tunnel_id: Tunnel ID
            tunnel_name: Tunnel name
            credentials: Base64 encoded credentials
            config_data: Base64 encoded config

        Returns:
            True if tunnel started successfully
        """
        if not self.tunnel_manager.save_tunnel_credentials(tunnel_id, credentials):
            logger.error("Failed to save tunnel credentials")
            return False

        if not self.tunnel_manager.save_tunnel_config(config_data, tunnel_id):
            logger.error("Failed to save tunnel config")
            return False

        logger.info("Tunnel config saved successfully")

        if not self.tunnel_manager.start_tunnel(tunnel_name):
            logger.error("Failed to start tunnel")
            return False

        logger.info("Tunnel started successfully")
        return True

    def stop_tunnel(self):
        """Stop the Cloudflare tunnel."""
        try:
            logger.info("Stopping tunnel...")
            self.tunnel_manager.stop_tunnel()
            logger.info("Tunnel stopped")
        except Exception as e:
            logger.error(f"Error stopping tunnel: {e}")

    def send_heartbeat(self, doctor_id: str):
        """
        Send a heartbeat to the backend.

        Args:
            doctor_id: Doctor's ID
        """
        try:
            if not doctor_id:
                return

            response = requests.post(
                f"{config.BACKEND_URL}/doctors/{doctor_id}/heartbeat",
                timeout=5,
            )

            if response.status_code in [200, 201]:
                logger.info("Heartbeat sent")
            else:
                logger.warning(f"Heartbeat failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")

    def start_heartbeat(self, doctor_id: str):
        """
        Start the heartbeat thread.

        Args:
            doctor_id: Doctor's ID
        """
        self.should_heartbeat = True
        heartbeat_interval = config.get_rpa_setting("heartbeat_interval_seconds", 300)

        def heartbeat_loop():
            while self.should_heartbeat and self.running:
                time.sleep(heartbeat_interval)
                if self.should_heartbeat and self.running:
                    self.send_heartbeat(doctor_id)

        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        logger.info(f"Heartbeat thread started (every {heartbeat_interval}s)")

    def stop_heartbeat(self):
        """Stop the heartbeat thread."""
        self.should_heartbeat = False

    def start(
        self,
        tunnel_id: str,
        tunnel_name: str,
        credentials: str,
        config_data: str,
        doctor_id: str,
    ) -> bool:
        """
        Start the complete agent (server + tunnel + heartbeat).

        Args:
            tunnel_id: Tunnel ID
            tunnel_name: Tunnel name
            credentials: Base64 encoded credentials
            config_data: Base64 encoded config
            doctor_id: Doctor's ID

        Returns:
            True if agent started successfully
        """
        self.running = True

        # Start server
        self.start_server()

        # Wait for server
        if not self.wait_for_server(max_attempts=15, delay=1):
            self.running = False
            return False

        # Start tunnel
        if not self.start_tunnel(tunnel_id, tunnel_name, credentials, config_data):
            self.running = False
            return False

        time.sleep(2)

        # Start heartbeat
        self.send_heartbeat(doctor_id)
        self.start_heartbeat(doctor_id)

        return True

    def stop(self):
        """Stop the agent."""
        self.running = False
        self.stop_heartbeat()
        self.stop_tunnel()
        logger.info("Agent stopped")
