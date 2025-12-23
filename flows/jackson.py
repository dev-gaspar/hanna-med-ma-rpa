"""
Jackson Health Flow - Patient list capture for Jackson Health System.
"""

from datetime import datetime

import pyautogui
import pydirectinput
import pyperclip

from config import config
from core.s3_client import get_s3_client
from core.vdi_input import stoppable_sleep

from .base_flow import BaseFlow


class JacksonFlow(BaseFlow):
    """RPA flow for Jackson Health patient list capture."""

    FLOW_NAME = "Jackson Health"
    FLOW_TYPE = "jackson_health_patient_list_capture"

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()

    @property
    def username(self):
        """Get username from Jackson credentials."""
        creds = self.get_credentials_for_system("JACKSON")
        if "username" not in creds:
            raise Exception("Jackson credentials missing 'username' field")
        return creds["username"]

    @property
    def password(self):
        """Get password from Jackson credentials."""
        creds = self.get_credentials_for_system("JACKSON")
        if "password" not in creds:
            raise Exception("Jackson credentials missing 'password' field")
        return creds["password"]

    def execute(self):
        """Execute all Jackson Health flow steps."""
        self.step_1_tab()
        self.step_2_powered()
        self.step_3_open_download()
        self.step_4_username()
        self.step_5_password()
        self.step_6_login_ok()
        self.step_7_patient_list()
        self.step_8_hospital_tab()
        screenshots = self.step_9_capture()
        self.step_10_close_cerner()
        self.step_11_vdi_tab()

        return screenshots

    def notify_completion(self, screenshots):
        """Notify n8n of successful completion."""
        payload = {
            "execution_id": self.execution_id,
            "status": "completed",
            "type": self.FLOW_TYPE,
            "total_screenshots": len(screenshots),
            "screenshots": screenshots,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
        }
        response = self._send_to_list_webhook_n8n(payload)
        print(f"\n[N8N] Notification sent - Status: {response.status_code}")
        return response

    # --- Flow Steps ---

    def step_1_tab(self):
        """Click Jackson Tab."""
        self.set_step("STEP_1_TAB_JACKSON")
        print("\n[STEP 1] Clicking Jackson Tab")

        jackson_tab = self.wait_for_element(
            config.get_rpa_setting("images.jackson_tab"),
            timeout=config.get_timeout("default", 60),
            description="Jackson Tab",
        )
        if not jackson_tab:
            raise Exception("Jackson Tab not found")

        if not self.safe_click(jackson_tab, "Jackson Tab"):
            raise Exception("Failed to click on Jackson Tab")

        stoppable_sleep(3)
        print("[STEP 1] Jackson Tab clicked")
        return True

    def step_2_powered(self):
        """Click Powered Jackson."""
        self.set_step("STEP_2_POWERED_JACKSON")
        print("\n[STEP 2] Clicking Powered Jackson")

        powered_jackson = self.wait_for_element(
            config.get_rpa_setting("images.jackson_powered"),
            timeout=config.get_timeout("default", 60),
            description="Powered Jackson",
            confidence=0.9,
        )
        if not powered_jackson:
            raise Exception("Powered Jackson not found")

        if not self.safe_click(powered_jackson, "Powered Jackson"):
            raise Exception("Failed to click on Powered Jackson")

        stoppable_sleep(3)
        print("[STEP 2] Powered Jackson clicked")
        return True

    def step_3_open_download(self):
        """Open Download Powered."""
        self.set_step("STEP_3_OPEN_DOWNLOAD")
        print("\n[STEP 3] Opening Download")

        open_download = self.wait_for_element(
            config.get_rpa_setting("images.jackson_open_download"),
            timeout=config.get_timeout("default", 60),
            description="Open Download",
            confidence=0.9,
        )
        if not open_download:
            raise Exception("Open Download not found")

        if not self.safe_click(open_download, "Open Download"):
            raise Exception("Failed to click on Open Download")

        stoppable_sleep(5)
        print("[STEP 3] Download opened")
        return True

    def step_4_username(self):
        """Enter Username."""
        self.set_step("STEP_4_USERNAME")
        print("\n[STEP 4] Entering Username")

        username_input = self.wait_for_element(
            config.get_rpa_setting("images.jackson_username"),
            timeout=config.get_timeout("default", 60),
            description="Username Input",
        )
        if not username_input:
            raise Exception("Username input not found")

        if not self.safe_click(username_input, "Username Input"):
            raise Exception("Failed to click on Username Input")

        stoppable_sleep(1)
        pyautogui.write(self.username)
        stoppable_sleep(2)
        print("[STEP 4] Username entered")
        return True

    def step_5_password(self):
        """Enter Password using clipboard paste (handles @ and special chars)."""
        self.set_step("STEP_5_PASSWORD")
        print("\n[STEP 5] Entering Password")

        password_input = self.wait_for_element(
            config.get_rpa_setting("images.jackson_password"),
            timeout=config.get_timeout("default", 60),
            description="Password Input",
            confidence=0.9,
        )
        if not password_input:
            raise Exception("Password input not found")

        if not self.safe_click(password_input, "Password Input"):
            raise Exception("Failed to click on Password Input")

        stoppable_sleep(1)

        # Use clipboard paste to handle @ and special characters properly
        pyperclip.copy("")
        stoppable_sleep(0.3)
        pyperclip.copy(self.password)
        stoppable_sleep(0.3)

        # Paste with Ctrl+V
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("v")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")

        stoppable_sleep(2)
        print("[STEP 5] Password entered")
        return True

    def step_6_login_ok(self):
        """Click Login OK."""
        self.set_step("STEP_6_LOGIN_OK")
        print("\n[STEP 6] Clicking Login OK")

        login_ok = self.wait_for_element(
            config.get_rpa_setting("images.jackson_login_ok"),
            timeout=config.get_timeout("default", 60),
            description="Login OK button",
        )
        if not login_ok:
            raise Exception("Login OK button not found")

        if not self.safe_click(login_ok, "Login OK"):
            raise Exception("Failed to click on Login OK")

        stoppable_sleep(5)
        print("[STEP 6] Login completed")
        return True

    def step_7_patient_list(self):
        """Click Patient List Tab, handling any information modals."""
        self.set_step("STEP_7_PATIENT_LIST")
        print("\n[STEP 7] Clicking Patient List Tab")

        # Define handler for the acknowledge modal that may appear
        def handle_acknowledge_modal(location):
            """Handler to dismiss the information modal by clicking Acknowledge."""
            self.safe_click(location, "Acknowledge Button")
            stoppable_sleep(2)

        # Define handler for the announcement modal
        def handle_announcement_modal(location):
            """Handler to dismiss announcement: check 'don't show' and close."""
            # First click "Don't show again" checkbox
            dont_show = self.wait_for_element(
                config.get_rpa_setting("images.jackson_announcement_dont_show"),
                timeout=5,
                description="Don't Show Again checkbox",
            )
            if dont_show:
                self.safe_click(dont_show, "Don't Show Again")
                stoppable_sleep(1)

            # Then close the announcement
            close_btn = self.wait_for_element(
                config.get_rpa_setting("images.jackson_announcement_close"),
                timeout=5,
                description="Close Announcement",
            )
            if close_btn:
                self.safe_click(close_btn, "Close Announcement")
                stoppable_sleep(2)

        # Define handler for the info modal that may appear after login
        def handle_info_modal(location):
            """Handler to dismiss info modal by pressing Enter."""
            print("[STEP 7] Info modal detected - pressing Enter to dismiss")
            pydirectinput.press("enter")
            stoppable_sleep(2)

        # Use robust_wait_for_element to handle modals if they appear
        handlers = {
            config.get_rpa_setting("images.jackson_acknowledge"): (
                "Information Modal (Acknowledge)",
                handle_acknowledge_modal,
            ),
            config.get_rpa_setting("images.jackson_announcement_modal"): (
                "Announcement Modal",
                handle_announcement_modal,
            ),
            config.get_rpa_setting("images.jackson_info_modal"): (
                "Info Modal (Enter)",
                handle_info_modal,
            ),
        }

        patient_list = self.robust_wait_for_element(
            config.get_rpa_setting("images.jackson_patient_list"),
            target_description="Patient List Tab",
            handlers=handlers,
            timeout=config.get_timeout("default", 60),
        )
        if not patient_list:
            raise Exception("Patient List Tab not found")

        if not self.safe_click(patient_list, "Patient List Tab"):
            raise Exception("Failed to click on Patient List Tab")

        stoppable_sleep(3)
        print("[STEP 7] Patient List opened")
        return True

    def step_8_hospital_tab(self):
        """Click Hospital Tab."""
        self.set_step("STEP_8_HOSPITAL_TAB")
        print("\n[STEP 8] Clicking Hospital Tab")

        hospital_tab = self.wait_for_element(
            config.get_rpa_setting("images.jackson_hospital_tab"),
            timeout=config.get_timeout("default", 60),
            description="Hospital Tab",
        )
        if not hospital_tab:
            raise Exception("Hospital Tab not found")

        if not self.safe_click(hospital_tab, "Hospital Tab"):
            raise Exception("Failed to click on Hospital Tab")

        stoppable_sleep(3)
        print("[STEP 8] Hospital Tab clicked")
        return True

    def step_9_capture(self):
        """Capture Screenshot."""
        self.set_step("STEP_9_SCREENSHOT")
        print("\n[STEP 9] Capturing Screenshot")

        screenshot_data = self.s3_client.capture_screenshot_for_hospital(
            "South Florida Foot And Ankle Institut", "Hospital_1", 1, self.execution_id
        )
        return [screenshot_data]

    def step_10_close_cerner(self):
        """Close Cerner."""
        self.set_step("STEP_10_CLOSE_CERNER")
        print("\n[STEP 10] Closing Cerner")

        close_button = self.wait_for_element(
            config.get_rpa_setting("images.jackson_cerner_close"),
            timeout=config.get_timeout("default", 60),
            description="Cerner Close button",
            confidence=0.95,
        )
        if not close_button:
            raise Exception("Cerner Close button not found")

        if not self.safe_click(close_button, "Cerner Close button"):
            raise Exception("Failed to click on Cerner Close button")

        stoppable_sleep(5)
        print("[STEP 10] Cerner closed")
        return True

    def step_11_vdi_tab(self):
        """Click VDI Desktop Tab."""
        self.set_step("STEP_11_VDI_TAB")
        print("\n[STEP 11] Clicking VDI Desktop Tab")

        vdi_tab = self.wait_for_element(
            config.get_rpa_setting("images.jackson_vdi_tab"),
            timeout=config.get_timeout("default", 60),
            description="VDI Desktop Tab",
        )
        if not vdi_tab:
            raise Exception("VDI Desktop Tab not found")

        if not self.safe_click(vdi_tab, "VDI Desktop Tab"):
            raise Exception("Failed to click on VDI Desktop Tab")

        stoppable_sleep(2)
        print("[STEP 11] VDI Desktop Tab clicked")
        return True
