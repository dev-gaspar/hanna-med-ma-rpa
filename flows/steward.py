"""
Steward Health Flow - Patient list recovery for Steward Health System.
"""

import os
from datetime import datetime

import pyautogui
import pydirectinput
import pyperclip

from config import config
from core.rpa_engine import rpa_state
from core.s3_client import get_s3_client
from core.vdi_input import type_with_clipboard, press_key_vdi, stoppable_sleep
from logger import logger

from .base_flow import BaseFlow


class StewardFlow(BaseFlow):
    """RPA flow for Steward Health list recovery."""

    FLOW_NAME = "Steward Health"
    FLOW_TYPE = "steward_list_recovery"

    def __init__(self):
        super().__init__()
        self.s3_client = get_s3_client()

    @property
    def email(self):
        """Get email from Steward credentials."""
        creds = self.get_credentials_for_system("STEWARD")
        if "email" not in creds:
            raise Exception("Steward credentials missing 'email' field")
        return creds["email"]

    @property
    def password(self):
        """Get password from Steward credentials."""
        creds = self.get_credentials_for_system("STEWARD")
        if "password" not in creds:
            raise Exception("Steward credentials missing 'password' field")
        return creds["password"]

    def execute(self):
        """Execute all Steward Health flow steps."""
        self._log_start()

        self.step_1_tab()
        self.step_2_favorite()
        self.step_3_meditech()
        self.step_4_login()
        self.step_5_open_session()
        self.step_6_navigate_menu_5()
        self.step_7_navigate_menu_6()
        self.step_8_click_lista()
        self.step_9_print_pdf()
        pdf_data = self.step_10_upload_pdf()
        self.step_11_close_pdf_tab()
        self.step_12_close_tab()
        self.step_13_close_modal()
        self.step_14_cancel_modal()
        self.step_15_close_meditech()
        self.step_16_tab_logged_out()
        self.step_17_close_tab_final()
        self.step_18_url()
        self.step_19_vdi_tab()

        return pdf_data

    def _log_start(self):
        """Log flow start."""
        logger.info("=" * 80)
        logger.info("STEWARD LIST RECOVERY RPA FLOW - STARTED")
        logger.info("=" * 80)
        logger.info(f"Execution ID: {self.execution_id}")
        logger.info(f"Sender: {self.sender}")
        logger.info(f"Instance: {self.instance}")
        logger.info(f"Trigger Type: {self.trigger_type}")
        logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Screen Resolution: {pyautogui.size()}")
        logger.info("=" * 80)

    def notify_completion(self, pdf_data):
        """Notify n8n of successful completion."""
        payload = {
            "execution_id": self.execution_id,
            "status": "completed",
            "type": self.FLOW_TYPE,
            "pdf_url": pdf_data["pdf_url"],
            "filename": pdf_data["filename"],
            "timestamp": pdf_data["timestamp"],
            "sender": self.sender,
            "instance": self.instance,
            "trigger_type": self.trigger_type,
            "doctor_name": self.doctor_name,
        }
        response = self._send_to_list_webhook_n8n(payload)
        logger.info(f"[N8N] Notification sent - Status: {response.status_code}")
        logger.info(f"[SUCCESS] PDF URL: {pdf_data['pdf_url']}")
        return response

    # --- Flow Steps ---

    def step_1_tab(self):
        """Click Steward Tab."""
        self.set_step("STEP_1_TAB_STEWARD")
        logger.info("[STEP 1] Clicking Steward Tab")

        steward_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_tab"),
            timeout=config.get_timeout("default", 60),
            description="Steward Tab",
        )
        if not steward_tab:
            raise Exception("Steward Tab not found")

        if not self.safe_click(steward_tab, "Steward Tab"):
            raise Exception("Failed to click on Steward Tab")

        stoppable_sleep(3)
        logger.info("[STEP 1] Steward Tab clicked")
        return True

    def step_2_favorite(self):
        """Click Favorite Steward."""
        self.set_step("STEP_2_FAVORITE_STEWARD")
        logger.info("[STEP 2] Clicking Favorite Steward")

        favorite = self.wait_for_element(
            config.get_rpa_setting("images.steward_favorite"),
            timeout=config.get_timeout("default", 60),
            description="Favorite Steward",
        )
        if not favorite:
            raise Exception("Favorite Steward not found")

        if not self.safe_click(favorite, "Favorite Steward"):
            raise Exception("Failed to click on Favorite Steward")

        stoppable_sleep(3)
        logger.info("[STEP 2] Favorite Steward clicked")
        return True

    def step_3_meditech(self):
        """Click Meditech."""
        self.set_step("STEP_3_MEDITECH")
        logger.info("[STEP 3] Clicking Meditech")

        meditech = self.wait_for_element(
            config.get_rpa_setting("images.steward_meditech"),
            timeout=config.get_timeout("default", 60),
            description="Meditech",
        )
        if not meditech:
            raise Exception("Meditech not found")

        if not self.safe_click(meditech, "Meditech"):
            raise Exception("Failed to click on Meditech")

        stoppable_sleep(5)
        logger.info("[STEP 3] Meditech clicked")
        return True

    def step_4_login(self):
        """
        Login with 'Windows Key Trick' (Using Ctrl+Esc) to force synchronization.
        Optimized: Detects location before syncing to minimize delays.
        """
        self.set_step("STEP_4_LOGIN")
        logger.info("[STEP 4] Login - Windows Key Sync Strategy")

        # --- PHASE 1: LOGIN WINDOW (EMAIL) ---
        login_window = self.wait_for_element(
            config.get_rpa_setting("images.steward_login_window"),
            timeout=120,
            description="Login Window",
        )

        if not login_window:
            # Recovery attempt with F5
            press_key_vdi("f5")
            stoppable_sleep(5)
            login_window = self.wait_for_element(
                config.get_rpa_setting("images.steward_login_window"), timeout=30
            )
            if not login_window:
                raise Exception("Login window not found")

        # Initial click for focus
        center_login = pyautogui.center(login_window)
        pyautogui.click(center_login)
        stoppable_sleep(1)

        logger.info("[LOGIN] Typing Email...")
        type_with_clipboard(self.email)
        stoppable_sleep(1.0)
        press_key_vdi("enter")

        # --- PHASE 2: PASSWORD PREPARATION (CRITICAL SPACE) ---
        logger.info("[LOGIN] Waiting for password screen...")

        # Wait and locate field BEFORE starting synchronization
        password_window = self.wait_for_element(
            config.get_rpa_setting("images.steward_password_window"),
            timeout=120,
            description="Password Input Field",
        )
        if not password_window:
            raise Exception("Password Window not found")

        # Save coordinates to use just before pasting
        password_click_target = pyautogui.center(password_window)

        # --- PHASE 3: COPY PASSWORD (LOCAL) ---
        logger.info("[LOGIN] Copying Password to Local Clipboard...")

        pyperclip.copy("")
        stoppable_sleep(0.5)
        pyperclip.copy(self.password)

        # --- PHASE 4: START MENU TRICK (FORCE SYNC) ---
        logger.info("[LOGIN] Executing Start Menu Dance (Ctrl+Esc) to force sync...")

        # Ensure neutral focus before the dance
        pyautogui.click(password_click_target)
        stoppable_sleep(0.5)

        # 1. Open Start Menu (Ctrl + Esc)
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("esc")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")

        stoppable_sleep(3.0)  # Wait for menu visualization

        # 2. Close Start Menu
        pydirectinput.press("esc")

        # 3. THE KEY 5 SECOND WAIT (Data transfer through VDI channel)
        logger.info("[LOGIN] Waiting 5s for sync as requested...")
        stoppable_sleep(5.0)

        # --- PHASE 5: CLICK AND PASTE (FAST) ---
        logger.info("[LOGIN] Clicking Password Field (Refocus)...")
        pyautogui.click(password_click_target)

        # Small technical pause for click to register focus
        stoppable_sleep(0.2)

        logger.info("[LOGIN] Pasting Password...")
        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.1)
        pydirectinput.press("v")
        stoppable_sleep(0.1)
        pydirectinput.keyUp("ctrl")

        stoppable_sleep(2.0)

        # --- PHASE 6: SUBMIT ---
        logger.info("[LOGIN] Submitting...")
        press_key_vdi("enter")

        stoppable_sleep(8)
        logger.info("[STEP 4] Login sequence completed")
        return True

    def step_5_open_session(self):
        """Click to open Meditech session, handling already-open sessions."""
        self.set_step("STEP_5_OPEN_SESSION")
        logger.info("[STEP 5] Opening Meditech session")

        # Check if a session is already open (obstacle)
        if self._check_element_exists(
            config.get_rpa_setting("images.steward_status_sesion_abierta")
        ):
            logger.info("[STEP 5] Session already open - resetting...")
            self._reset_existing_session()

        # Now proceed with normal session opening
        sesion_meditech = self.wait_for_element(
            config.get_rpa_setting("images.steward_sesion_meditech"),
            timeout=config.get_timeout("default", 60),
            description="Meditech Session",
        )
        if not sesion_meditech:
            raise Exception("Meditech Session button not found")

        if not self.safe_click(sesion_meditech, "Meditech Session"):
            raise Exception("Failed to click on Meditech Session")

        stoppable_sleep(5)
        logger.info("[STEP 5] Meditech session opened")
        return True

    def _check_element_exists(self, image_path, confidence=None):
        """Quickly check if an element exists on screen without waiting."""
        if confidence is None:
            confidence = self.confidence
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            return location is not None
        except pyautogui.ImageNotFoundException:
            return False
        except Exception:
            return False

    def _reset_existing_session(self):
        """Reset an already-open Meditech session."""
        # Click Reset button
        reset_btn = self.wait_for_element(
            config.get_rpa_setting("images.steward_reset_sesion"),
            timeout=10,
            description="Reset Session Button",
        )
        if not reset_btn:
            raise Exception("Reset Session button not found")

        if not self.safe_click(reset_btn, "Reset Session"):
            raise Exception("Failed to click Reset Session")

        stoppable_sleep(2)

        # Click Terminate button in the modal
        terminate_btn = self.wait_for_element(
            config.get_rpa_setting("images.steward_terminate_sesion"),
            timeout=10,
            description="Terminate Session Button",
        )
        if not terminate_btn:
            raise Exception("Terminate Session button not found")

        if not self.safe_click(terminate_btn, "Terminate Session"):
            raise Exception("Failed to click Terminate Session")

        # Wait longer for UI to refresh after terminating session
        logger.info("[STEP 5] Waiting for UI to refresh after terminate...")
        stoppable_sleep(5)
        logger.info("[STEP 5] Existing session terminated")

    def _handle_sign_list_popup(self, location):
        """Handler to close the Sign List popup that appears when there are pending documents.

        Also handles the Warning modal that may appear after closing Sign List,
        clicking 'Leave Now' button if it appears.
        """
        logger.info("[SIGN LIST] Sign List popup detected - closing it...")

        # Close the popup using steward_close_meditech
        close_btn = self.wait_for_element(
            config.get_rpa_setting("images.steward_close_meditech"),
            timeout=10,
            description="Close Meditech (Sign List)",
        )
        if close_btn:
            self.safe_click(close_btn, "Close Sign List")
            stoppable_sleep(2)
            logger.info("[SIGN LIST] Sign List popup closed")

            # Check if Warning modal appeared after closing Sign List
            self._handle_warning_leave_now_modal()

    def _handle_warning_leave_now_modal(self):
        """Handle the Warning modal that may appear after closing Sign List.

        This modal has a 'Leave Now' button that needs to be clicked to dismiss it.
        """
        logger.info("[SIGN LIST] Checking for Warning modal...")

        leave_now_btn = self.wait_for_element(
            config.get_rpa_setting("images.steward_leave_now_btn"),
            timeout=5,
            description="Leave Now Button",
        )

        if leave_now_btn:
            logger.info("[SIGN LIST] Warning modal detected - clicking Leave Now...")
            self.safe_click(leave_now_btn, "Leave Now")
            stoppable_sleep(2)
            logger.info("[SIGN LIST] Warning modal dismissed successfully")
        else:
            logger.info("[SIGN LIST] No Warning modal detected - continuing")

    def _get_sign_list_handlers(self):
        """Get handlers for Sign List popup obstacle.

        Includes both Sign List image variants to maximize detection.
        """
        return {
            config.get_rpa_setting("images.steward_sign_list"): (
                "Sign List Popup",
                self._handle_sign_list_popup,
            ),
            config.get_rpa_setting("images.steward_sign_list_obstacle"): (
                "Sign List Obstacle",
                self._handle_sign_list_popup,
            ),
        }

    def step_6_navigate_menu_5(self):
        """Wait for menu to load and navigate (step 5)."""
        self.set_step("STEP_6_MENU_5")
        logger.info("[STEP 6] Navigating menu (step 5)")

        menu = self.wait_for_element(
            config.get_rpa_setting("images.steward_load_menu_5"),
            timeout=config.get_timeout("default", 60),
            description="Menu (step 5)",
        )
        if not menu:
            raise Exception("Menu (step 5) not found")

        stoppable_sleep(2)

        # Right arrow, Down arrow, Enter
        press_key_vdi("right")
        press_key_vdi("down")
        press_key_vdi("enter")
        stoppable_sleep(3)

        logger.info("[STEP 6] Menu navigation (step 5) completed")
        return True

    def step_7_navigate_menu_6(self):
        """Wait for menu to load and navigate (step 6), handling Sign List popup."""
        self.set_step("STEP_7_MENU_6")
        logger.info("[STEP 7] Navigating menu (step 6)")

        # Use robust_wait_for_element to handle Sign List popup if it appears
        menu = self.robust_wait_for_element(
            config.get_rpa_setting("images.steward_load_menu_6"),
            target_description="Menu (step 6)",
            handlers=self._get_sign_list_handlers(),
            timeout=config.get_timeout("default", 60),
        )
        if not menu:
            raise Exception("Menu (step 6) not found")

        stoppable_sleep(2)

        # Click directly on menu to open it instead of Tab+Enter
        if not self.safe_click(menu, "Menu dropdown"):
            raise Exception("Failed to click on Menu")
        stoppable_sleep(1)

        # 5 times arrow down
        for _ in range(5):
            press_key_vdi("down")

        press_key_vdi("enter")
        stoppable_sleep(0.5)

        # Tab, Enter
        press_key_vdi("tab")
        press_key_vdi("enter")
        stoppable_sleep(0.5)

        # 3 tabs
        for _ in range(3):
            press_key_vdi("tab")

        press_key_vdi("enter")
        stoppable_sleep(0.5)

        # 2 tabs
        for _ in range(2):
            press_key_vdi("tab")

        press_key_vdi("enter")
        stoppable_sleep(3)

        logger.info("[STEP 7] Menu navigation (step 6) completed")
        return True

    def step_8_click_lista(self):
        """Click on the lista."""
        self.set_step("STEP_8_LISTA")
        logger.info("[STEP 8] Clicking on lista")

        lista = self.wait_for_element(
            config.get_rpa_setting("images.steward_lista"),
            timeout=config.get_timeout("default", 60),
            description="Lista",
        )
        if not lista:
            raise Exception("Lista not found")

        if not self.safe_click(lista, "Lista"):
            raise Exception("Failed to click on Lista")

        stoppable_sleep(2)
        logger.info("[STEP 8] Lista clicked")
        return True

    def step_9_print_pdf(self):
        """Print to PDF - Robust VDI Version with printer verification."""
        self.set_step("STEP_9_PRINT_PDF")
        logger.info("[STEP 9] Printing to PDF (Robust Ctrl+P)")

        # 1. Ensure focus on document
        screen_width, screen_height = pyautogui.size()
        pyautogui.click(screen_width // 2, screen_height // 2)
        stoppable_sleep(1.5)

        # 2. Send Ctrl + P "Manually" (Hardware Simulation)
        logger.info("[PRINT] Sending Ctrl + P via DirectInput...")

        pydirectinput.keyDown("ctrl")
        stoppable_sleep(0.5)

        pydirectinput.press("p")
        stoppable_sleep(0.5)

        pydirectinput.keyUp("ctrl")

        # 3. Wait for print dialog to load
        logger.info("[PRINT] Waiting for Print Dialog...")
        stoppable_sleep(8.0)

        # 4. Verify Horizon Printer is selected
        if not self._verify_horizon_printer():
            logger.info("[PRINT] Horizon Printer not selected - selecting it...")
            self._select_horizon_printer()
        else:
            logger.info("[PRINT] Horizon Printer already selected")

        # 5. Click Print button to start printing (avoid focus issues with Enter)
        logger.info("[PRINT] Clicking Print button...")
        print_btn = self.wait_for_element(
            config.get_rpa_setting("images.steward_print_btn"),
            timeout=10,
            description="Print Button",
        )
        if not print_btn:
            raise Exception("Print button not found")

        if not self.safe_click(print_btn, "Print Button"):
            raise Exception("Failed to click Print button")
        stoppable_sleep(4.0)

        for i in range(2):
            logger.info(f"[PRINT] Dialog navigation enter {i+1}...")
            press_key_vdi("enter")
            stoppable_sleep(3.0)

        logger.info("[PRINT] Selecting action (Left)...")
        press_key_vdi("left")
        stoppable_sleep(1.5)

        logger.info("[PRINT] Final Save command...")
        press_key_vdi("enter")

        logger.info("[PRINT] Waiting for file save...")
        stoppable_sleep(10.0)

        logger.info("[STEP 9] PDF Print sequence finished")
        return True

    def _verify_horizon_printer(self):
        """Check if Horizon Printer is currently selected."""
        return self._check_element_exists(
            config.get_rpa_setting("images.steward_horizon_printer_ok")
        )

    def _select_horizon_printer(self):
        """Select Horizon Printer from the dropdown."""
        # Click on Save PDF dropdown to open options
        save_pdf_dropdown = self.wait_for_element(
            config.get_rpa_setting("images.steward_save_pdf_dropdown"),
            timeout=10,
            description="Save PDF Dropdown",
        )
        if not save_pdf_dropdown:
            raise Exception("Save PDF dropdown not found")

        if not self.safe_click(save_pdf_dropdown, "Save PDF Dropdown"):
            raise Exception("Failed to click Save PDF dropdown")

        stoppable_sleep(2)

        # Select Horizon Printer option
        horizon_option = self.wait_for_element(
            config.get_rpa_setting("images.steward_horizon_printer_option"),
            timeout=10,
            description="Horizon Printer Option",
        )
        if not horizon_option:
            raise Exception("Horizon Printer option not found")

        if not self.safe_click(horizon_option, "Horizon Printer"):
            raise Exception("Failed to select Horizon Printer")

        stoppable_sleep(2)
        logger.info("[PRINT] Horizon Printer selected")

    def step_10_upload_pdf(self):
        """Find and upload the PDF file."""
        self.set_step("STEP_10_UPLOAD_PDF")
        logger.info("[STEP 10] Uploading PDF file")

        # Get the desktop path
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        pdf_filename = "GOLDEN SUN Portal.pdf"
        pdf_path = os.path.join(desktop_path, pdf_filename)

        # Check if file exists
        if not os.path.exists(pdf_path):
            raise Exception(f"PDF file not found at: {pdf_path}")

        # Upload to S3
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_filename = f"steward/{self.execution_id}/list_{timestamp}.pdf"

        self.s3_client.upload_pdf(pdf_path, s3_filename)
        pdf_url = self.s3_client.generate_presigned_url(s3_filename)

        logger.info(f"[STEP 10] PDF uploaded: {pdf_url}")
        return {
            "pdf_url": pdf_url,
            "filename": s3_filename,
            "timestamp": timestamp,
        }

    def step_11_close_pdf_tab(self):
        """Close PDF tab."""
        self.set_step("STEP_11_CLOSE_PDF_TAB")
        logger.info("[STEP 11] Closing PDF tab")

        pdf_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_tab_pdf"),
            timeout=config.get_timeout("default", 60),
            description="PDF Tab",
        )
        if not pdf_tab:
            raise Exception("PDF Tab not found")

        # Right click on the tab
        center = pyautogui.center(pdf_tab)
        pyautogui.rightClick(center)
        stoppable_sleep(1)

        logger.info("[STEP 11] PDF tab right-clicked")
        return True

    def step_12_close_tab(self):
        """Close tab."""
        self.set_step("STEP_12_CLOSE_TAB")
        logger.info("[STEP 12] Closing tab")

        close_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_close_tab"),
            timeout=config.get_timeout("default", 60),
            description="Close Tab",
        )
        if not close_tab:
            raise Exception("Close Tab not found")

        if not self.safe_click(close_tab, "Close Tab"):
            raise Exception("Failed to click on Close Tab")

        stoppable_sleep(2)
        logger.info("[STEP 12] Tab closed")
        return True

    def step_13_close_modal(self):
        """Close modal."""
        self.set_step("STEP_13_CLOSE_MODAL")
        logger.info("[STEP 13] Closing modal")

        close_modal = self.wait_for_element(
            config.get_rpa_setting("images.steward_close_modal"),
            timeout=config.get_timeout("default", 60),
            description="Close Modal",
        )
        if not close_modal:
            raise Exception("Close Modal not found")

        if not self.safe_click(close_modal, "Close Modal"):
            raise Exception("Failed to click on Close Modal")

        stoppable_sleep(2)
        logger.info("[STEP 13] Modal closed")
        return True

    def step_14_cancel_modal(self):
        """Cancel modal."""
        self.set_step("STEP_14_CANCEL_MODAL")
        logger.info("[STEP 14] Canceling modal")

        cancel_modal = self.wait_for_element(
            config.get_rpa_setting("images.steward_cancel_modal"),
            timeout=config.get_timeout("default", 60),
            description="Cancel Modal",
        )
        if not cancel_modal:
            raise Exception("Cancel Modal not found")

        if not self.safe_click(cancel_modal, "Cancel Modal"):
            raise Exception("Failed to click on Cancel Modal")

        stoppable_sleep(2)
        logger.info("[STEP 14] Modal canceled")
        return True

    def step_15_close_meditech(self):
        """Close Meditech."""
        self.set_step("STEP_15_CLOSE_MEDITECH")
        logger.info("[STEP 15] Closing Meditech")

        close_meditech = self.wait_for_element(
            config.get_rpa_setting("images.steward_close_meditech"),
            timeout=config.get_timeout("default", 60),
            description="Close Meditech",
        )
        if not close_meditech:
            raise Exception("Close Meditech not found")

        if not self.safe_click(close_meditech, "Close Meditech"):
            raise Exception("Failed to click on Close Meditech")

        stoppable_sleep(2)

        # Click in the same location again (as per the process)
        if not self.safe_click(close_meditech, "Close Meditech (second click)"):
            raise Exception("Failed to click on Close Meditech (second click)")

        stoppable_sleep(2)
        logger.info("[STEP 15] Meditech closed")
        return True

    def step_16_tab_logged_out(self):
        """Right click on logged out tab."""
        self.set_step("STEP_16_TAB_LOGGED_OUT")
        logger.info("[STEP 16] Right clicking on logged out tab")

        logged_out_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_tab_logged_out"),
            timeout=config.get_timeout("default", 60),
            description="Logged Out Tab",
        )
        if not logged_out_tab:
            raise Exception("Logged Out Tab not found")

        # Right click on the tab
        center = pyautogui.center(logged_out_tab)
        pyautogui.rightClick(center)
        stoppable_sleep(1)

        logger.info("[STEP 16] Logged out tab right-clicked")
        return True

    def step_17_close_tab_final(self):
        """Close tab (final)."""
        self.set_step("STEP_17_CLOSE_TAB_FINAL")
        logger.info("[STEP 17] Closing tab (final)")

        close_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_close_tab"),
            timeout=config.get_timeout("default", 60),
            description="Close Tab",
        )
        if not close_tab:
            raise Exception("Close Tab not found")

        if not self.safe_click(close_tab, "Close Tab (final)"):
            raise Exception("Failed to click on Close Tab (final)")

        stoppable_sleep(2)
        logger.info("[STEP 17] Tab closed (final)")
        return True

    def step_18_url(self):
        """Right click on URL and reset."""
        self.set_step("STEP_18_URL")
        logger.info("[STEP 18] Right clicking on URL")

        url_field = self.wait_for_element(
            config.get_rpa_setting("images.steward_url"),
            timeout=config.get_timeout("default", 60),
            description="URL Field",
        )
        if not url_field:
            raise Exception("URL Field not found")

        # Click on the URL field
        center = pyautogui.center(url_field)
        pyautogui.click(center)
        stoppable_sleep(0.5)

        # Select all existing text and delete it
        pyautogui.hotkey("ctrl", "a")
        stoppable_sleep(0.2)

        # Type the URL using clipboard for VDI compatibility
        url = "https://horizon.steward.org/portal/webclient/#/home"
        logger.info(f"[STEP 18] Typing URL using clipboard: {url}")
        type_with_clipboard(url)
        stoppable_sleep(0.5)

        # Press Enter
        press_key_vdi("enter")
        stoppable_sleep(3)

        logger.info("[STEP 18] URL reset")
        return True

    def step_19_vdi_tab(self):
        """Click VDI Desktop Tab."""
        self.set_step("STEP_19_VDI_TAB")
        logger.info("[STEP 19] Clicking VDI Desktop Tab")

        vdi_tab = self.wait_for_element(
            config.get_rpa_setting("images.steward_vdi_desktop_tab"),
            timeout=config.get_timeout("default", 60),
            description="VDI Desktop Tab",
        )
        if not vdi_tab:
            raise Exception("VDI Desktop Tab not found")

        if not self.safe_click(vdi_tab, "VDI Desktop Tab"):
            raise Exception("Failed to click on VDI Desktop Tab")

        stoppable_sleep(2)
        logger.info("[STEP 19] VDI Desktop Tab clicked")
        return True
