"""
Baptist Health Flow - Patient list capture for Baptist Health System.
"""

from datetime import datetime

import pyautogui

from config import config
from core.rpa_engine import rpa_state
from core.s3_client import get_s3_client
from core.vdi_input import stoppable_sleep

from .base_flow import BaseFlow


class BaptistFlow(BaseFlow):
    """RPA flow for Baptist Health patient list capture."""

    FLOW_NAME = "Baptist Health"
    FLOW_TYPE = "baptist_health_patient_list_capture"

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()

    def execute(self):
        """Execute all Baptist Health flow steps."""
        self.step_1_open_vdi_desktop()
        self.step_2_open_edge()
        self.step_3_wait_pineapple_connect()
        self.step_4_open_menu()
        self.step_5_scroll_modal()
        self.step_6_click_cerner()
        self.step_7_wait_cerner_login()
        self.step_8_click_favorites()
        self.step_9_click_powerchart()
        self.step_10_wait_powerchart_open()
        screenshots = self.step_11_capture_patient_lists()
        self.step_12_close_powerchart()
        self.step_13_close_horizon()
        self.step_14_accept_alert()
        self.step_15_return_to_start()

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
        }
        response = self._send_to_list_webhook_n8n(payload)
        print(f"\n[N8N] Notification sent - Status: {response.status_code}")

        print(f"[SUCCESS] Total screenshots: {len(screenshots)}")
        for idx, screenshot in enumerate(screenshots, 1):
            print(
                f"[SUCCESS] {idx}. {screenshot['display_name']} - "
                f"{screenshot['hospital_name']}: {screenshot['screenshot_url']}"
            )
        return response

    # --- Flow Steps ---

    def step_1_open_vdi_desktop(self):
        """Open VDI Desktop."""
        self.set_step("STEP_1_OPEN_VDI")
        print("\n[STEP 1] Opening VDI Desktop")

        vdi_icon = self.wait_for_element(
            config.get_rpa_setting("images.vdi_icon"),
            timeout=config.get_timeout("vdi_open", 30),
            description="VDI Desktop icon",
        )
        if not vdi_icon:
            raise Exception("VDI Desktop icon not found")

        if not self.safe_click(vdi_icon, "VDI Desktop"):
            raise Exception("Failed to click on VDI Desktop")

        stoppable_sleep(5)
        print("[STEP 1] VDI Desktop started")
        return True

    def step_2_open_edge(self):
        """Open Microsoft Edge with fallback to close windows and show desktop."""
        self.set_step("STEP_2_OPEN_EDGE")
        print("\n[STEP 2] Opening Edge")

        edge_icon = self.wait_for_element(
            config.get_rpa_setting("images.edge_icon"),
            timeout=config.get_timeout("edge_open", 300),
            description="Edge icon",
        )

        # Fallback: If Edge icon not found, close all windows and try again
        if not edge_icon:
            print("[STEP 2] Edge icon not found - attempting to close all windows")
            self._close_all_windows_and_show_desktop()

            # Retry finding Edge icon after showing desktop
            edge_icon = self.wait_for_element(
                config.get_rpa_setting("images.edge_icon"),
                timeout=30,
                description="Edge icon (retry)",
            )
            if not edge_icon:
                raise Exception("Edge icon not found after closing windows")

        edge_center = pyautogui.center(edge_icon)
        pyautogui.doubleClick(edge_center)
        print("[STEP 2] Edge opened")
        return True

    def _close_all_windows_and_show_desktop(self):
        """Close all open windows using Alt+F4 until desktop is visible."""
        print("[FALLBACK] Closing all open windows...")

        max_attempts = 10  # Maximum windows to close
        windows_closed = 0

        for attempt in range(max_attempts):
            self.check_stop()

            # Check if Edge icon is now visible (means we're at desktop)
            try:
                edge_check = pyautogui.locateOnScreen(
                    config.get_rpa_setting("images.edge_icon"),
                    confidence=self.confidence,
                )
                if edge_check:
                    print(
                        f"[FALLBACK] Desktop reached after closing {windows_closed} window(s)"
                    )
                    return
            except Exception:
                pass  # Image not found, continue closing

            # Close the current window
            print(f"[FALLBACK] Closing window {attempt + 1}...")
            pyautogui.hotkey("alt", "F4")
            windows_closed += 1
            stoppable_sleep(0.5)

            # Handle dialogs with keyboard shortcuts
            # Enter: Confirms "Leave" in Chrome/Edge dialogs
            pyautogui.press("enter")
            stoppable_sleep(0.3)

            # N: For "No/Don't Save" in Windows native apps (Notepad, etc)
            pyautogui.press("n")
            stoppable_sleep(0.3)

        print(f"[FALLBACK] Closed {windows_closed} windows")

    def _handler_edge_login(self, location_of_email_field):
        """Handle Edge login page."""
        print("[HANDLER] Handling Edge login")

        self.safe_click(location_of_email_field, "email field")
        stoppable_sleep(1)

        saved_password = self.wait_for_element(
            config.get_rpa_setting("images.saved_password"),
            timeout=10,
            description="saved password",
        )
        if not saved_password:
            raise Exception("Saved password not found")

        self.safe_click(saved_password, "saved password")
        stoppable_sleep(1)
        pyautogui.press("enter")
        stoppable_sleep(2)
        pyautogui.press("enter")
        stoppable_sleep(3)
        pyautogui.press("enter")
        stoppable_sleep(5)
        print("[HANDLER] Login completed")

    def step_3_wait_pineapple_connect(self):
        """Wait for pineappleconnect.net to open, handling obstacles."""
        self.set_step("STEP_3_PINEAPPLE")
        print("\n[STEP 3] Waiting for Pineapple Connect")

        obstacle_handlers = {
            config.get_rpa_setting("images.email_input"): (
                "Login page",
                self._handler_edge_login,
            ),
        }

        menu_icon = self.robust_wait_for_element(
            target_image_path=config.get_rpa_setting("images.pineapple_menu"),
            target_description="Pineapple Connect menu",
            handlers=obstacle_handlers,
            timeout=config.get_timeout("pineapple_connect", 300),
        )

        if not menu_icon:
            raise Exception("Pineapple Connect did not load")
        print("[STEP 3] Pineapple Connect loaded")
        return True

    def step_4_open_menu(self):
        """Open 3-dots menu."""
        self.set_step("STEP_4_MENU")
        print("\n[STEP 4] Opening menu")

        menu_icon = self.wait_for_element(
            config.get_rpa_setting("images.pineapple_menu"),
            timeout=30,
            description="3-dots menu",
        )
        if not menu_icon:
            raise Exception("Menu not found")

        if not self.safe_click(menu_icon, "3-dots menu"):
            raise Exception("Failed to open the menu")

        modal = self.wait_for_element(
            config.get_rpa_setting("images.pineapple_modal"),
            timeout=10,
            description="menu modal",
        )
        if not modal:
            raise Exception("Modal did not open")

        print("[STEP 4] Menu opened")
        return True

    def step_5_scroll_modal(self):
        """Scroll in the modal."""
        self.set_step("STEP_5_SCROLL")
        print("\n[STEP 5] Scrolling in modal")

        modal = self.wait_for_element(
            config.get_rpa_setting("images.pineapple_modal"),
            timeout=10,
            description="modal",
        )
        if not modal:
            raise Exception("Modal not found")

        modal_center = pyautogui.center(modal)
        pyautogui.moveTo(modal_center)
        stoppable_sleep(0.5)

        for _ in range(3):
            self.check_stop()
            pyautogui.scroll(-300)
            stoppable_sleep(0.2)

        stoppable_sleep(1)
        print("[STEP 5] Scroll completed")
        return True

    def step_6_click_cerner(self):
        """Click on Cerner BHSF."""
        self.set_step("STEP_6_CERNER")
        print("\n[STEP 6] Searching for Cerner BHSF")

        cerner = self.wait_for_element(
            config.get_rpa_setting("images.cerner"),
            timeout=config.get_timeout("cerner_open", 120),
            description="Cerner BHSF",
        )
        if not cerner:
            raise Exception("Cerner BHSF not found")

        if not self.safe_click(cerner, "Cerner BHSF"):
            raise Exception("Failed to click on Cerner")

        stoppable_sleep(2)
        print("[STEP 6] Cerner opened")
        return True

    def _handler_log_on_cerner(self, location):
        """Click on the 'Log On to Cerner' button with delay to handle auto-redirect."""
        print("[HANDLER] Waiting before clicking 'Log On to Cerner'...")
        # Wait 1 second before clicking to handle cases where page auto-redirects
        stoppable_sleep(1)
        self.safe_click(location, "Log On to Cerner")
        stoppable_sleep(2)

    def step_7_wait_cerner_login(self):
        """Wait for automatic login to Cerner."""
        self.set_step("STEP_7_CERNER_LOGIN")
        print("\n[STEP 7] Waiting for Cerner login")

        obstacle_handlers = {
            config.get_rpa_setting("images.log_on_cerner"): (
                "Log On to Cerner button",
                self._handler_log_on_cerner,
            )
        }

        favorites_tab = self.robust_wait_for_element(
            target_image_path=config.get_rpa_setting("images.favorites_tab"),
            target_description="Favorites tab",
            handlers=obstacle_handlers,
            timeout=config.get_timeout("cerner_login", 120),
        )
        if not favorites_tab:
            raise Exception("Cerner login did not complete")

        print("[STEP 7] Session started in Cerner")
        return True

    def step_8_click_favorites(self):
        """Click on Favorites."""
        self.set_step("STEP_8_FAVORITES")
        print("\n[STEP 8] Opening Favorites")

        favorites = self.wait_for_element(
            config.get_rpa_setting("images.favorites_tab"),
            timeout=10,
            description="Favorites tab",
        )
        if not favorites:
            raise Exception("Favorites not found")

        if not self.safe_click(favorites, "Favorites"):
            raise Exception("Failed to open Favorites")

        stoppable_sleep(2)
        print("[STEP 8] Favorites opened")
        return True

    def step_9_click_powerchart(self):
        """Click on Powerchart P574 BHS_FL."""
        self.set_step("STEP_9_POWERCHART")
        print("\n[STEP 9] Searching for PowerChart")

        powerchart = self.wait_for_element(
            config.get_rpa_setting("images.powerchart"),
            timeout=config.get_timeout("powerchart_open", 120),
            description="Powerchart P574 BHS_FL",
        )
        if not powerchart:
            raise Exception("PowerChart not found")

        if not self.safe_click(powerchart, "PowerChart"):
            raise Exception("Failed to click on PowerChart")

        stoppable_sleep(5)
        print("[STEP 9] PowerChart downloaded")
        return True

    def step_10_wait_powerchart_open(self):
        """Wait for PowerChart to open."""
        self.set_step("STEP_10_WAIT_POWERCHART")
        print("\n[STEP 10] Waiting for PowerChart to open")

        patient_list_btn = self.wait_for_element(
            config.get_rpa_setting("images.patient_list"),
            timeout=config.get_timeout("powerchart_open", 120),
            description="Patient List button",
        )
        if not patient_list_btn:
            raise Exception("PowerChart did not open correctly")

        print("[STEP 10] PowerChart opened")
        return True

    def step_11_capture_patient_lists(self):
        """Capture patient list from configured hospitals."""
        self.set_step("STEP_11_CAPTURE_SCREENSHOTS")
        print("\n[STEP 11] Capturing patient lists")
        screenshots = []

        patient_list_btn = self.wait_for_element(
            config.get_rpa_setting("images.patient_list"),
            timeout=10,
            description="Patient List button",
            auto_click=True,
        )
        if not patient_list_btn:
            raise Exception("Patient List not found")
        stoppable_sleep(3)

        # Get hospitals from configuration
        hospitals = config.get_hospitals()

        for idx, hospital in enumerate(hospitals, 1):
            hospital_full_name = hospital.get("name", f"Unknown Hospital {idx}")
            display_name = hospital.get("display_name", f"Hospital_{idx}")
            hospital_index = hospital.get("index", idx)
            tab_image = hospital.get("tab_image")

            print(f"\n[STEP 11.{idx}] Processing {display_name} - {hospital_full_name}")

            # First hospital is already visible
            if idx == 1:
                screenshot_data = self.s3_client.capture_screenshot_for_hospital(
                    hospital_full_name, display_name, hospital_index, self.execution_id
                )
                screenshots.append(screenshot_data)
            else:
                # Switch to other hospitals if tab_image is configured
                if tab_image:
                    hospital_tab = self.wait_for_element(
                        tab_image,
                        timeout=10,
                        confidence=0.9,
                        description=f"{display_name} tab",
                    )
                    if hospital_tab:
                        self.safe_click(hospital_tab, f"{display_name} tab")
                        stoppable_sleep(2)
                        screenshot_data = (
                            self.s3_client.capture_screenshot_for_hospital(
                                hospital_full_name,
                                display_name,
                                hospital_index,
                                self.execution_id,
                            )
                        )
                        screenshots.append(screenshot_data)
                    else:
                        print(f"[STEP 11.{idx}] {display_name} tab not found, skipping")
                else:
                    print(
                        f"[STEP 11.{idx}] No tab image configured for {display_name}, skipping"
                    )

        print(f"\n[STEP 11] Captures completed ({len(screenshots)} hospitals)")
        return screenshots

    def step_12_close_powerchart(self):
        """Close PowerChart and browser."""
        self.set_step("STEP_12_CLOSE_POWERCHART")
        print("\n[STEP 12] Closing PowerChart and Edge")

        pyautogui.hotkey("alt", "f4")
        print("[STEP 12] PowerChart closed")
        stoppable_sleep(5)

        pyautogui.hotkey("alt", "f4")
        print("[STEP 12] Edge closed")
        stoppable_sleep(5)
        return True

    def step_13_close_horizon(self):
        """Close Horizon Client."""
        self.set_step("STEP_13_CLOSE_HORIZON")
        print("\n[STEP 13] Closing Horizon")

        pyautogui.hotkey("ctrl", "alt")
        stoppable_sleep(0.5)

        horizon_menu = self.wait_for_element(
            config.get_rpa_setting("images.horizon_menu"),
            timeout=config.get_timeout("horizon_close", 120),
            confidence=0.9,
            description="Horizon menu",
        )
        if not horizon_menu:
            raise Exception("Horizon menu not found")

        self.safe_click(horizon_menu, "Horizon menu")
        stoppable_sleep(1)

        close_session = self.wait_for_element(
            config.get_rpa_setting("images.horizon_close"),
            timeout=config.get_timeout("horizon_close", 120),
            description="close session",
        )
        if not close_session:
            raise Exception("Close session option not found")

        self.safe_click(close_session, "close session")
        stoppable_sleep(1)
        print("[STEP 13] Session closed")
        return True

    def step_14_accept_alert(self):
        """Accept alert."""
        self.set_step("STEP_14_ACCEPT_ALERT")
        print("\n[STEP 14] Accepting alert")

        accept_btn = self.wait_for_element(
            config.get_rpa_setting("images.accept_alert"),
            timeout=config.get_timeout("horizon_close", 120),
            description="Accept button",
        )
        if not accept_btn:
            raise Exception("Accept button not found")

        self.safe_click(accept_btn, "Accept button")
        stoppable_sleep(1)
        print("[STEP 14] Alert accepted")
        return True

    def step_15_return_to_start(self):
        """Confirm return to starting point."""
        self.set_step("STEP_15_RETURN")
        print("\n[STEP 15] Back at VDI Desktop")
        return True
