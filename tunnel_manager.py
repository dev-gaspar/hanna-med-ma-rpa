"""
Tunnel Manager - Manages Cloudflare tunnel
"""

import os
import subprocess
import platform
import base64
import json
from pathlib import Path
from typing import Optional, Dict
import requests
from config import config
from logger import logger


def _get_subprocess_startupinfo():
    """Get startupinfo for subprocess to hide console windows on Windows"""
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None


def _get_subprocess_creation_flags():
    """Get creation flags for subprocess to hide console windows on Windows"""
    if platform.system() == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


class TunnelManager:
    """Manages embedded Cloudflare tunnel"""

    def __init__(self):
        self.app_dir = config.get_app_dir()
        self.bin_dir = config.get_bin_dir()
        self.cloudflared_dir = config.get_cloudflared_dir()
        self.cloudflared_exe = self._get_cloudflared_path()
        self.tunnel_process: Optional[subprocess.Popen] = None

        logger.info("TunnelManager initialized")
        logger.info(f"App dir: {self.app_dir}")
        logger.info(f"Bin dir: {self.bin_dir}")
        logger.info(f"Cloudflared dir: {self.cloudflared_dir}")

        # Create necessary directories
        try:
            self.bin_dir.mkdir(parents=True, exist_ok=True)
            self.cloudflared_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Directories created successfully")
        except Exception as e:
            logger.error(f"Error creating directories: {e}", exc_info=True)
            raise

    def _get_cloudflared_path(self) -> Path:
        """Get path to cloudflared executable"""
        if platform.system() == "Windows":
            return self.bin_dir / "cloudflared.exe"
        else:
            return self.bin_dir / "cloudflared"

    def is_cloudflared_available(self) -> bool:
        """Check if cloudflared is available"""
        return self.cloudflared_exe.exists()

    def download_cloudflared(self) -> bool:
        """
        Download cloudflared if not available (fallback - usually comes with installer)
        """
        if self.is_cloudflared_available():
            return True

        logger.info("Cloudflared not found. Downloading...")

        try:
            # Detect OS and architecture
            system = platform.system().lower()
            machine = platform.machine().lower()

            # Download URLs
            urls = {
                "windows": {
                    "amd64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
                    "386": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
                },
                "linux": {
                    "amd64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                    "x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                    "arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
                },
                "darwin": {
                    "amd64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
                    "arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
                },
            }

            # Normalize architecture
            if machine in ["x86_64", "amd64"]:
                arch = "amd64"
            elif machine in ["i386", "i686"]:
                arch = "386"
            elif machine in ["aarch64", "arm64"]:
                arch = "arm64"
            else:
                arch = "amd64"  # Default

            url = urls.get(system, {}).get(arch)
            if not url:
                logger.error(f"No URL found for {system}/{arch}")
                return False

            # Download
            logger.info(f"Downloading from {url}...")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            # Save
            with open(self.cloudflared_exe, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Set execution permissions (Linux/Mac)
            if system != "windows":
                os.chmod(self.cloudflared_exe, 0o755)

            logger.info("Cloudflared downloaded successfully")
            return True

        except Exception as e:
            logger.error(f"Error downloading cloudflared: {e}")
            return False

    def save_tunnel_credentials(self, tunnel_id: str, credentials_base64: str) -> bool:
        """
        Save tunnel credentials downloaded from backend

        Args:
            tunnel_id: Tunnel ID
            credentials_base64: Credentials in base64

        Returns:
            True if saved successfully
        """
        try:
            logger.info(f"Saving tunnel credentials for tunnel ID: {tunnel_id}")

            # Decode base64
            credentials_json = base64.b64decode(credentials_base64).decode("utf-8")
            credentials = json.loads(credentials_json)

            # Save to file
            credentials_file = self.cloudflared_dir / f"{tunnel_id}.json"
            with open(credentials_file, "w") as f:
                json.dump(credentials, f, indent=2)

            logger.info(f"Credentials saved: {credentials_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving credentials: {e}", exc_info=True)
            return False

    def save_tunnel_config(self, config_base64: str, tunnel_id: str) -> bool:
        """
        Save tunnel config.yml file

        Args:
            config_base64: Configuration in base64
            tunnel_id: Tunnel ID to fix credentials path

        Returns:
            True if saved successfully
        """
        try:
            logger.info("Saving tunnel config")

            # Decode base64
            config_yaml = base64.b64decode(config_base64).decode("utf-8")

            # Fix credentials-file path
            credentials_file = self.cloudflared_dir / f"{tunnel_id}.json"
            import re

            # Convert Windows path to forward slashes
            credentials_path_fixed = str(credentials_file).replace("\\", "/")
            config_yaml = re.sub(
                r"credentials-file:.*",
                f"credentials-file: {credentials_path_fixed}",
                config_yaml,
            )

            # Fix localhost to 127.0.0.1 for Windows compatibility
            config_yaml = config_yaml.replace("http://localhost:", "http://127.0.0.1:")

            # Save to file
            config_file = self.cloudflared_dir / "config.yml"
            with open(config_file, "w") as f:
                f.write(config_yaml)

            logger.info(f"Config saved: {config_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving config: {e}", exc_info=True)
            return False

    def start_tunnel(self, tunnel_name: str) -> bool:
        """
        Start Cloudflare tunnel

        Args:
            tunnel_name: Tunnel name (e.g., rpa-dr.test)

        Returns:
            True if tunnel started successfully
        """
        try:
            logger.info(f"Starting tunnel: {tunnel_name}")

            if not self.is_cloudflared_available():
                logger.warning("Cloudflared not available, attempting download...")
                if not self.download_cloudflared():
                    logger.error("Failed to download cloudflared")
                    return False

            # Verify config.yml exists
            config_file = self.cloudflared_dir / "config.yml"
            if not config_file.exists():
                logger.error(f"config.yml not found at {config_file}")
                return False

            # Command to start tunnel
            cmd = [
                str(self.cloudflared_exe),
                "tunnel",
                "--config",
                str(config_file),
                "run",
                tunnel_name,
            ]

            logger.info(f"Tunnel command: {' '.join(cmd)}")

            # Start process (hide console window on Windows)
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=_get_subprocess_startupinfo(),
                creationflags=_get_subprocess_creation_flags(),
            )

            logger.info(f"Tunnel started (PID: {self.tunnel_process.pid})")

            # Monitor tunnel output
            import threading

            def monitor_stdout():
                try:
                    for line in iter(self.tunnel_process.stdout.readline, b""):
                        if line:
                            decoded = line.decode("utf-8", errors="ignore").strip()
                            if decoded:
                                logger.info(f"[CLOUDFLARED] {decoded}")
                                if (
                                    "registered" in decoded.lower()
                                    or "connected" in decoded.lower()
                                ):
                                    logger.info("Tunnel connected to Cloudflare")
                except Exception as e:
                    logger.error(f"Error reading stdout: {e}", exc_info=True)

            def monitor_stderr():
                try:
                    for line in iter(self.tunnel_process.stderr.readline, b""):
                        if line:
                            decoded = line.decode("utf-8", errors="ignore").strip()
                            if decoded:
                                logger.warning(f"[CLOUDFLARED-ERR] {decoded}")
                except Exception as e:
                    logger.error(f"Error reading stderr: {e}", exc_info=True)

            stdout_thread = threading.Thread(target=monitor_stdout, daemon=True)
            stderr_thread = threading.Thread(target=monitor_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            # Give it a moment to start
            import time

            time.sleep(0.5)

            # Check if process is still alive
            if self.tunnel_process.poll() is not None:
                logger.error(
                    f"Tunnel process died immediately (exit code: {self.tunnel_process.returncode})"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Error starting tunnel: {e}", exc_info=True)
            return False

    def stop_tunnel(self):
        """Stop Cloudflare tunnel"""
        if self.tunnel_process:
            try:
                logger.info("Stopping tunnel...")

                # On Windows, try to kill the process tree
                if platform.system() == "Windows":
                    try:
                        # Try to kill using taskkill (kills process tree)
                        subprocess.run(
                            [
                                "taskkill",
                                "/F",
                                "/T",
                                "/PID",
                                str(self.tunnel_process.pid),
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                            startupinfo=_get_subprocess_startupinfo(),
                            creationflags=_get_subprocess_creation_flags(),
                        )
                        logger.info("Tunnel stopped using taskkill")
                    except Exception as e:
                        logger.warning(f"Taskkill failed, using terminate: {e}")
                        self.tunnel_process.terminate()
                        self.tunnel_process.wait(timeout=3)
                else:
                    # On Unix, terminate is sufficient
                    self.tunnel_process.terminate()
                    self.tunnel_process.wait(timeout=5)
                    logger.info("Tunnel stopped")

            except subprocess.TimeoutExpired:
                logger.warning("Forcing tunnel closure with kill...")
                self.tunnel_process.kill()
                self.tunnel_process.wait()
            except Exception as e:
                logger.error(f"Error stopping tunnel: {e}")
            finally:
                self.tunnel_process = None
                logger.info("Tunnel process cleared")

    def is_tunnel_running(self) -> bool:
        """Check if tunnel is running"""
        if self.tunnel_process is None:
            return False
        return self.tunnel_process.poll() is None

    def get_tunnel_logs(self) -> str:
        """Get tunnel logs"""
        if self.tunnel_process and self.tunnel_process.stderr:
            try:
                return self.tunnel_process.stderr.read().decode(
                    "utf-8", errors="ignore"
                )
            except Exception:
                return ""
        return ""

    def setup_tunnel_from_backend(
        self, backend_url: str, username: str, password: str
    ) -> Dict:
        """
        Configure tunnel by downloading credentials from backend

        Args:
            backend_url: Backend URL (e.g., https://api.hannamedma.com)
            username: Doctor username
            password: Doctor password

        Returns:
            Dict with tunnel info or error
        """
        try:
            # Call RPA config endpoint
            response = requests.post(
                f"{backend_url}/doctors/rpa-config",
                json={"username": username, "password": password},
                timeout=30,
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Server error: {response.status_code}",
                }

            data = response.json()

            if not data.get("success"):
                return {"success": False, "error": "Invalid credentials"}

            # Extract data
            tunnel_info = data.get("tunnel", {})
            tunnel_id = tunnel_info.get("tunnelId")
            tunnel_name = tunnel_info.get("tunnelName")
            credentials = tunnel_info.get("credentials")
            config = tunnel_info.get("config")

            if not all([tunnel_id, tunnel_name, credentials, config]):
                return {"success": False, "error": "Incomplete data from server"}

            # Save credentials and config
            if not self.save_tunnel_credentials(tunnel_id, credentials):
                return {"success": False, "error": "Error saving credentials"}

            if not self.save_tunnel_config(config):
                return {"success": False, "error": "Error saving config"}

            # Start tunnel
            if not self.start_tunnel(tunnel_name):
                return {"success": False, "error": "Error starting tunnel"}

            return {
                "success": True,
                "tunnel_id": tunnel_id,
                "tunnel_name": tunnel_name,
                "hostname": tunnel_info.get("hostname"),
                "doctor": data.get("doctor", {}),
            }

        except requests.RequestException as e:
            return {"success": False, "error": f"Connection error: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
