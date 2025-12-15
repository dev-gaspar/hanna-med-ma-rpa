"""
Configuration Manager - Handles persistent storage of credentials and settings
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
import base64
from config import config


class ConfigManager:
    """Manages configuration persistence for the RPA agent"""

    def __init__(self):
        self.config_dir = config.get_app_dir()
        self.config_file = self.config_dir / "config.json"
        self.credentials_dir = config.get_cloudflared_dir()

        # Create directories if they don't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Optional[Dict[str, Any]]:
        """Load configuration from disk"""
        if not self.config_file.exists():
            return None

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return None

    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to disk"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def clear_config(self) -> bool:
        """Clear all configuration"""
        try:
            if self.config_file.exists():
                self.config_file.unlink()
            return True
        except Exception as e:
            print(f"Error clearing config: {e}")
            return False

    def save_tunnel_credentials(
        self, tunnel_id: str, credentials_b64: str, config_b64: str
    ) -> bool:
        """Save Cloudflare tunnel credentials and config"""
        try:
            # Save credentials file
            creds_file = self.credentials_dir / f"{tunnel_id}.json"
            creds_content = base64.b64decode(credentials_b64).decode("utf-8")
            with open(creds_file, "w", encoding="utf-8") as f:
                f.write(creds_content)

            # Save config.yml
            config_file = self.credentials_dir / "config.yml"
            config_content = base64.b64decode(config_b64).decode("utf-8")

            # Update config to use local path
            config_content = config_content.replace(
                "/path/to/.cloudflared/", str(self.credentials_dir) + os.sep
            )

            with open(config_file, "w", encoding="utf-8") as f:
                f.write(config_content)

            return True
        except Exception as e:
            print(f"Error saving tunnel credentials: {e}")
            return False

    def get_tunnel_config_path(self) -> str:
        """Get path to tunnel config file"""
        return str(self.credentials_dir / "config.yml")

    def has_valid_config(self) -> bool:
        """Check if valid configuration exists"""
        config = self.load_config()
        if not config:
            return False

        # Check required fields
        required = ["doctorId", "username", "accessToken", "rpaUrl", "tunnelId"]
        return all(field in config for field in required)

    def get_auto_start_enabled(self) -> bool:
        """Check if auto-start is enabled"""
        config = self.load_config()
        if not config:
            return False
        return config.get("autoStart", True)

    def set_auto_start(self, enabled: bool) -> bool:
        """Enable or disable auto-start"""
        config = self.load_config()
        if not config:
            return False

        config["autoStart"] = enabled
        return self.save_config(config)

    def update_last_seen(self):
        """Update last seen timestamp"""
        config = self.load_config()
        if config:
            from datetime import datetime

            config["lastSeen"] = datetime.now().isoformat()
            self.save_config(config)
