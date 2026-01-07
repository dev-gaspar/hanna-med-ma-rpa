"""
Configuration management with environment variables
"""

import os
import sys
import json
from pathlib import Path


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller"""
    try:
        base_path = sys._MEIPASS  # PyInstaller bundle
    except AttributeError:
        base_path = Path(__file__).parent  # Running from source

    full_path = Path(base_path) / relative_path
    return full_path


def load_env():
    """Load environment variables from .env file if exists"""
    env_file = get_resource_path(".env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load .env file on import
load_env()


class Config:
    """Application configuration with environment variables support"""

    BACKEND_URL = os.getenv("BACKEND_URL")
    APP_NAME = "HannaMedRPA"

    # Load RPA configuration from JSON
    _rpa_config_path = get_resource_path("rpa_config.json")
    RPA_CONFIG = {}

    if _rpa_config_path.exists():
        try:
            with open(_rpa_config_path, "r", encoding="utf-8") as f:
                RPA_CONFIG = json.load(f)
        except Exception:
            RPA_CONFIG = {}

    @staticmethod
    def get_app_dir() -> Path:
        """Get application directory based on OS"""
        if os.name == "nt":  # Windows
            app_data = Path(os.environ.get("APPDATA", ""))
            return app_data / Config.APP_NAME
        else:  # Linux/Mac
            return Path.home() / ".hannamed-rpa"

    @staticmethod
    def get_bin_dir() -> Path:
        """Get binary directory"""
        return Config.get_app_dir() / "bin"

    @staticmethod
    def get_cloudflared_dir() -> Path:
        """Get cloudflared config directory"""
        return Config.get_app_dir() / ".cloudflared"

    @staticmethod
    def get_logs_dir() -> Path:
        """Get logs directory"""
        return Config.get_app_dir() / "logs"

    @staticmethod
    def get_resource_path(relative_path: str) -> Path:
        """
        Get absolute path to a bundled resource (works for PyInstaller).
        Use this for accessing images, config files, etc.

        Example:
            image_path = config.get_resource_path('images/vdi_icon.png')
        """
        return get_resource_path(relative_path)

    @staticmethod
    def get_rpa_setting(key_path: str, default=None, resolution=None):
        """
        Get nested RPA config value using dot notation.

        Examples:
            get_rpa_setting('aws.bucket_name')
            get_rpa_setting('timeouts.default')
            get_rpa_setting('images.vdi_icon')

        Args:
            key_path: Dot-separated path to setting (e.g., 'aws.bucket_name')
            default: Default value if key not found
            resolution: Optional resolution override (e.g. "1024x768")

        Returns:
            Config value or default
        """
        keys = key_path.split(".")
        value = Config.RPA_CONFIG

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default

        # Handle environment variable placeholders like ${AWS_ACCESS_KEY_ID}
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.getenv(env_var, default)

        # If it's an image path, resolve it to absolute path and apply resolution
        if isinstance(value, str) and key_path.startswith("images."):
            # Get current resolution from config or use default
            res = resolution if resolution else Config.get_screen_resolution()
            # Replace {resolution} placeholder with actual resolution
            value = value.replace("{resolution}", res)
            return str(get_resource_path(value))

        return value if value is not None else default

    @staticmethod
    def get_screen_resolution():
        """Get configured screen resolution or default"""
        # Try to get from persisted config first (saved by user in GUI)
        from config_manager import ConfigManager

        cm = ConfigManager()
        saved_config = cm.load_config()
        if saved_config and "screen_resolution" in saved_config:
            return saved_config["screen_resolution"]

        # Otherwise use default from rpa_config.json
        return Config.RPA_CONFIG.get("screen_resolution", "1366x768")

    @staticmethod
    def set_screen_resolution(resolution: str):
        """Save screen resolution to persistent config"""
        from config_manager import ConfigManager

        cm = ConfigManager()
        config_data = cm.load_config() or {}
        config_data["screen_resolution"] = resolution
        return cm.save_config(config_data)

    @staticmethod
    def get_available_resolutions():
        """Get list of available screen resolutions"""
        return Config.RPA_CONFIG.get("available_resolutions", ["1366x768"])

    @staticmethod
    def get_hospitals():
        """Get list of configured hospitals with resolved image paths"""
        hospitals = Config.RPA_CONFIG.get("hospitals", [])
        resolution = Config.get_screen_resolution()

        # Resolve image paths for each hospital
        for hospital in hospitals:
            if "tab_image" in hospital and hospital["tab_image"] is not None:
                # Replace {resolution} placeholder with actual resolution
                tab_image = hospital["tab_image"].replace("{resolution}", resolution)
                hospital["tab_image"] = str(get_resource_path(tab_image))
        return hospitals

    @staticmethod
    def get_roi_center(emr_type: str, region_name: str) -> tuple:
        """
        Get the center coordinates of an ROI region.

        Args:
            emr_type: EMR type ('jackson' or 'baptist')
            region_name: Region name (e.g., 'notes_tree', 'patient_list')

        Returns:
            Tuple (x, y) of center coordinates, or None if not found
        """
        resolution = Config.get_screen_resolution()
        roi_regions = Config.RPA_CONFIG.get("roi_regions", {})

        emr_regions = roi_regions.get(emr_type, {})
        res_regions = emr_regions.get(resolution, {})
        region = res_regions.get(region_name)

        if not region:
            return None

        # Calculate center of region
        center_x = region["x"] + region["w"] // 2
        center_y = region["y"] + region["h"] // 2
        return (center_x, center_y)

    @staticmethod
    def get_rois_for_agent(emr_type: str, agent_name: str) -> list:
        """
        Get ROI regions configured for a specific agent.

        Args:
            emr_type: EMR type ('jackson' or 'baptist')
            agent_name: Agent name (e.g., 'patient_finder', 'report_finder')

        Returns:
            List of ROI dicts with x, y, w, h keys. Empty list if not configured.
        """
        resolution = Config.get_screen_resolution()
        roi_definitions = Config.RPA_CONFIG.get("roi_definitions", {})
        roi_regions = Config.RPA_CONFIG.get("roi_regions", {})

        # Get region names for this agent
        region_names = (
            roi_definitions.get(emr_type, {}).get(resolution, {}).get(agent_name, [])
        )
        if not region_names:
            return []

        # Get actual region coordinates
        regions = roi_regions.get(emr_type, {}).get(resolution, {})
        rois = []
        for name in region_names:
            if name in regions:
                rois.append(regions[name])

        return rois

    @staticmethod
    def get_timeout(timeout_name: str, default: int = 60) -> int:
        """Get specific timeout value in seconds"""
        return Config.get_rpa_setting(f"timeouts.{timeout_name}", default)


# Export singleton config instance
config = Config()
