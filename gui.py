import customtkinter as ctk
from tkinter import messagebox
import requests
import threading
import subprocess
import time
import sys
import platform
from pathlib import Path
import uvicorn
from config import config
from tunnel_manager import TunnelManager
from logger import logger
from services import AuthService
from services.lobby_service import start_lobby_service, stop_lobby_service

if platform.system() == "Windows":
    import winreg

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

PRIMARY_COLOR = "#53489E"
PRIMARY_HOVER = "#42397E"
SECONDARY_BG = "#F2F8FF"
SUCCESS_COLOR = "#10B981"
ERROR_COLOR = "#EF4444"


class RPAApplication(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Hanna-Med MA - Medical Assistant")
        self.geometry("500x500")
        self.resizable(False, False)

        self.center_window()

        self.doctor_data = None
        self.agent_running = False
        self.server_process = None
        self.tunnel_manager = TunnelManager()
        self.tunnel_config = None
        self.heartbeat_thread = None
        self.should_heartbeat = False
        self.auth_service = AuthService()

        self.show_login_screen()

    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def clear_window(self):
        for widget in self.winfo_children():
            widget.destroy()

    def show_login_screen(self):
        self.clear_window()

        main_frame = ctk.CTkFrame(self, fg_color=SECONDARY_BG)
        main_frame.pack(expand=True, fill="both")

        content_frame = ctk.CTkFrame(
            main_frame, fg_color="white", corner_radius=12, width=380, height=420
        )
        content_frame.place(relx=0.5, rely=0.5, anchor="center")

        title_label = ctk.CTkLabel(
            content_frame,
            text="Hanna-Med MA",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=PRIMARY_COLOR,
        )
        title_label.pack(pady=(30, 5))

        subtitle_label = ctk.CTkLabel(
            content_frame,
            text="RPA Agent - Doctor Login",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        )
        subtitle_label.pack(pady=(0, 30))

        username_label = ctk.CTkLabel(
            content_frame,
            text="Username",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        username_label.pack(pady=(0, 5), padx=30, fill="x")

        self.username_entry = ctk.CTkEntry(
            content_frame,
            placeholder_text="Enter your username",
            height=38,
            font=ctk.CTkFont(size=13),
            border_color="#E5E7EB",
            fg_color="white",
        )
        self.username_entry.pack(pady=(0, 15), padx=30, fill="x")

        password_label = ctk.CTkLabel(
            content_frame,
            text="Password",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        password_label.pack(pady=(0, 5), padx=30, fill="x")

        self.password_entry = ctk.CTkEntry(
            content_frame,
            placeholder_text="Enter your password",
            show="•",
            height=38,
            font=ctk.CTkFont(size=13),
            border_color="#E5E7EB",
            fg_color="white",
        )
        self.password_entry.pack(pady=(0, 20), padx=30, fill="x")

        self.password_entry.bind("<Return>", lambda e: self.perform_login())

        self.status_label = ctk.CTkLabel(
            content_frame, text="", font=ctk.CTkFont(size=12), text_color=ERROR_COLOR
        )
        self.status_label.pack(pady=(0, 10))

        self.login_button = ctk.CTkButton(
            content_frame,
            text="Sign In",
            command=self.perform_login,
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8,
            fg_color=PRIMARY_COLOR,
            hover_color=PRIMARY_HOVER,
        )
        self.login_button.pack(pady=(0, 20), padx=30, fill="x")

        footer_label = ctk.CTkLabel(
            content_frame,
            text="Hanna-Med MA RPA v1.1",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        footer_label.pack(pady=(0, 20))

    def perform_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showerror("Error", "Please enter username and password")
            return

        self.login_button.configure(state="disabled", text="Signing in...")
        self.status_label.configure(text="Authenticating...", text_color="#F59E0B")
        self.update()

        thread = threading.Thread(target=self.authenticate, args=(username, password))
        thread.daemon = True
        thread.start()

    def authenticate(self, username, password):
        """Authenticate using AuthService."""
        result = self.auth_service.login(username, password)

        if result["success"]:
            self.doctor_data = result["doctor"]
            self.after(0, self.show_dashboard)
        else:
            error_msg = result.get("error", "Authentication failed")
            self.after(0, lambda: self.show_login_error(error_msg))

    def show_login_error(self, message):
        self.login_button.configure(state="normal", text="Sign In")
        self.status_label.configure(text=message, text_color=ERROR_COLOR)

    def show_dashboard(self):
        self.clear_window()

        main_frame = ctk.CTkFrame(self, fg_color=SECONDARY_BG)
        main_frame.pack(expand=True, fill="both")

        header_frame = ctk.CTkFrame(main_frame, fg_color="white")
        header_frame.pack(fill="x", padx=20, pady=(20, 15))

        welcome_label = ctk.CTkLabel(
            header_frame,
            text=f"Welcome, {self.doctor_data.get('name', 'Doctor')}",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=PRIMARY_COLOR,
        )
        welcome_label.pack(side="left", padx=15, pady=12)

        logout_button = ctk.CTkButton(
            header_frame,
            text="Log Out",
            command=self.logout,
            width=100,
            height=32,
            font=ctk.CTkFont(size=12),
            fg_color="#6B7280",
            hover_color="#4B5563",
            corner_radius=6,
        )
        logout_button.pack(side="right", padx=15, pady=12)

        status_frame = ctk.CTkFrame(main_frame, fg_color="white")
        status_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.agent_status_label = ctk.CTkLabel(
            status_frame,
            text="System Stopped",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=ERROR_COLOR,
        )
        self.agent_status_label.pack(pady=(30, 10))

        self.status_message = ctk.CTkLabel(
            status_frame,
            text="The assistant is off. Click 'Start' to activate it.",
            font=ctk.CTkFont(size=13),
            text_color="#6B7280",
        )
        self.status_message.pack(pady=(0, 30))

        self.toggle_button = ctk.CTkButton(
            status_frame,
            text="Start Assistant",
            command=self.toggle_agent,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=SUCCESS_COLOR,
            hover_color="#059669",
            corner_radius=10,
        )
        self.toggle_button.pack(pady=(0, 30), padx=40, fill="x")

        settings_frame = ctk.CTkFrame(main_frame, fg_color="white")
        settings_frame.pack(fill="x", padx=20, pady=(0, 20))

        settings_title = ctk.CTkLabel(
            settings_frame,
            text="Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PRIMARY_COLOR,
            anchor="w",
        )
        settings_title.pack(pady=(15, 15), padx=20, fill="x")

        # Resolution selector
        resolution_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        resolution_frame.pack(fill="x", padx=20, pady=(0, 10))

        resolution_label = ctk.CTkLabel(
            resolution_frame,
            text="Screen Resolution:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#374151",
            anchor="w",
        )
        resolution_label.pack(side="left", padx=(0, 10))

        available_resolutions = config.get_available_resolutions()
        current_resolution = config.get_screen_resolution()

        self.resolution_var = ctk.StringVar(value=current_resolution)
        resolution_menu = ctk.CTkOptionMenu(
            resolution_frame,
            variable=self.resolution_var,
            values=available_resolutions,
            command=self.on_resolution_change,
            font=ctk.CTkFont(size=12),
            width=140,
            fg_color=PRIMARY_COLOR,
            button_color=PRIMARY_HOVER,
        )
        resolution_menu.pack(side="left")

        if platform.system() == "Windows":
            self.autostart_var = ctk.BooleanVar(value=self.is_autostart_enabled())
            autostart_checkbox = ctk.CTkCheckBox(
                settings_frame,
                text="Start automatically with Windows",
                variable=self.autostart_var,
                command=self.toggle_autostart,
                font=ctk.CTkFont(size=12),
                text_color="#374151",
            )
            autostart_checkbox.pack(pady=(5, 15), padx=20, anchor="w")
        else:
            # Add some padding if not on Windows
            ctk.CTkLabel(settings_frame, text="").pack(pady=7)

    def is_autostart_enabled(self) -> bool:
        if platform.system() != "Windows":
            return False

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            try:
                winreg.QueryValueEx(key, "HannaMedRPA")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception as e:
            logger.warning(f"Error checking auto-start: {e}")
            return False

    def on_resolution_change(self, new_resolution):
        """Handle resolution change"""
        try:
            # Save the new resolution to config
            if config.set_screen_resolution(new_resolution):
                logger.info(f"Resolution changed to: {new_resolution}")
                messagebox.showinfo(
                    "Resolution Updated",
                    f"Screen resolution set to {new_resolution}.\n\n"
                    "The new resolution will be used the next time the assistant starts.",
                )
            else:
                logger.error("Failed to save resolution")
                messagebox.showerror("Error", "Could not save resolution setting")
        except Exception as e:
            logger.error(f"Error changing resolution: {e}")
            messagebox.showerror("Error", f"Could not change resolution: {str(e)}")

    def toggle_autostart(self):
        if platform.system() != "Windows":
            return

        enabled = self.autostart_var.get()

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )

            if enabled:
                if getattr(sys, "frozen", False):
                    exe_path = sys.executable
                else:
                    exe_path = f'"{sys.executable}" "{Path(__file__).absolute()}"'

                winreg.SetValueEx(key, "HannaMedRPA", 0, winreg.REG_SZ, exe_path)
                logger.info(f"Auto-start enabled: {exe_path}")
                messagebox.showinfo(
                    "Auto-start Enabled",
                    "The assistant will start automatically when you turn on your computer.",
                )
            else:
                try:
                    winreg.DeleteValue(key, "HannaMedRPA")
                    logger.info("Auto-start disabled")
                    messagebox.showinfo(
                        "Auto-start Disabled",
                        "The assistant will no longer start automatically.",
                    )
                except FileNotFoundError:
                    pass

            winreg.CloseKey(key)

        except Exception as e:
            logger.error(f"Error toggling auto-start: {e}")
            messagebox.showerror("Error", f"Could not change settings: {str(e)}")
            self.autostart_var.set(not enabled)

    def update_status_message(self, message):
        if hasattr(self, "status_message"):
            self.status_message.configure(text=message)

    def update_status_display(self, running: bool):
        if running:
            self.agent_status_label.configure(
                text="System Active", text_color=SUCCESS_COLOR
            )
            self.status_message.configure(
                text="The assistant is running. You will receive your reports automatically."
            )
            self.toggle_button.configure(
                text="Stop Assistant", fg_color=ERROR_COLOR, hover_color="#DC2626"
            )
        else:
            self.agent_status_label.configure(
                text="System Stopped", text_color=ERROR_COLOR
            )
            self.status_message.configure(
                text="The assistant is off. Click 'Start' to activate it."
            )
            self.toggle_button.configure(
                text="Start Assistant", fg_color=SUCCESS_COLOR, hover_color="#059669"
            )

    def toggle_agent(self):
        if self.agent_running:
            self.stop_agent()
        else:
            self.start_agent()

    def start_agent(self):
        if self.agent_running:
            return

        rpa_url = self.doctor_data.get("rpaUrl")
        if not rpa_url:
            messagebox.showerror("Error", "RPA URL not configured for this doctor")
            return

        self.update_status_message("Starting assistant...")
        self.agent_running = True

        self.toggle_button.configure(state="disabled", text="Starting...")
        self.agent_status_label.configure(
            text="Starting System...", text_color="#F59E0B"
        )

        thread = threading.Thread(target=self.run_agent)
        thread.daemon = True
        thread.start()

    def run_agent(self):
        try:
            logger.info(f"Starting RPA agent for {self.doctor_data.get('username')}")

            # Update UI - Downloading tunnel configuration
            self.after(
                0,
                lambda: self.update_status_message(
                    "Downloading tunnel configuration..."
                ),
            )
            self.after(0, lambda: self.update_idletasks())

            result = self.fetch_tunnel_config()

            if not result["success"]:
                error_msg = result["error"]
                logger.error(f"Failed to fetch tunnel config: {error_msg}")
                raise Exception(error_msg)

            tunnel_name = result.get("tunnel_name")
            logger.info(f"Tunnel config fetched: {tunnel_name}")

            # Update UI - Starting local server
            self.after(
                0, lambda: self.update_status_message("Starting local server...")
            )
            self.after(0, lambda: self.update_idletasks())

            self.start_fastapi_server()

            if not self.wait_for_server(max_attempts=15, delay=1):
                error_msg = "The local server could not be started"
                logger.error(error_msg)
                raise Exception(error_msg)

            logger.info("FastAPI server started")

            # Update UI - Connecting to system
            self.after(0, lambda: self.update_status_message("Connecting to system..."))
            self.after(0, lambda: self.update_idletasks())

            if not self.tunnel_manager.start_tunnel(tunnel_name):
                logger.error("Failed to start tunnel")
                raise Exception("Could not start connection tunnel")

            logger.info("Tunnel started successfully")
            time.sleep(2)

            # Update UI - Completed
            self.after(0, lambda: self.update_status_display(True))
            self.after(0, lambda: self.toggle_button.configure(state="normal"))
            self.after(0, lambda: self.update_idletasks())

            print(f"\nRPA Agent accessible at: {self.doctor_data.get('rpaUrl')}")

            # Start lobby verification service (runs every hour)
            start_lobby_service(interval_seconds=3600)
            logger.info("Lobby verification service started")

            # Send initial heartbeat and start heartbeat thread
            self.after(0, lambda: self.send_heartbeat())
            self.after(0, lambda: self.start_heartbeat_thread())

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Agent startup failed: {error_msg}", exc_info=True)
            self.after(
                0, lambda err=error_msg: self.update_status_message(f"Error: {err}")
            )
            self.after(
                0, lambda err=error_msg: messagebox.showerror("Startup Error", err)
            )
            self.after(0, self.reset_agent_state)

    def fetch_tunnel_config(self):
        try:
            logger.info(
                f"Fetching tunnel config for {self.doctor_data.get('username')}"
            )

            response = requests.post(
                f"{config.BACKEND_URL}/doctors/rpa-config",
                json={
                    "username": self.doctor_data.get("username"),
                    "password": self.doctor_data.get("_password", ""),
                },
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

            if not self.tunnel_manager.save_tunnel_credentials(tunnel_id, credentials):
                logger.error("Failed to save tunnel credentials")
                return {"success": False, "error": "Failed to save credentials"}

            if not self.tunnel_manager.save_tunnel_config(config_data, tunnel_id):
                logger.error("Failed to save tunnel config")
                return {"success": False, "error": "Failed to save config"}

            logger.info("Tunnel config saved successfully")

            return {"success": True, "tunnel_id": tunnel_id, "tunnel_name": tunnel_name}

        except Exception as e:
            logger.error(f"Exception in fetch_tunnel_config: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}

    def start_fastapi_server(self):
        def run_server():
            try:
                import app

                uvicorn.run(
                    app.app,
                    host="0.0.0.0",
                    port=8000,
                    log_config=None,
                    access_log=False,
                )
            except Exception as e:
                logger.error(f"Failed to start FastAPI server: {e}", exc_info=True)

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        logger.info("FastAPI server thread started")

    def wait_for_server(self, max_attempts=10, delay=1):
        import socket

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

    def send_heartbeat(self):
        try:
            doctor_id = self.doctor_data.get("id")
            if not doctor_id:
                return

            response = requests.post(
                f"{config.BACKEND_URL}/doctors/{doctor_id}/heartbeat", timeout=5
            )

            if response.status_code in [200, 201]:
                logger.info("Heartbeat sent")
            else:
                logger.warning(f"Heartbeat failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")

    def start_heartbeat_thread(self):
        self.should_heartbeat = True
        heartbeat_interval = config.get_rpa_setting("heartbeat_interval_seconds", 300)

        def heartbeat_loop():
            while self.should_heartbeat and self.agent_running:
                time.sleep(heartbeat_interval)
                if self.should_heartbeat and self.agent_running:
                    self.send_heartbeat()

        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        logger.info(f"Heartbeat thread started (every {heartbeat_interval}s)")

    def stop_agent(self):
        if not self.agent_running:
            return

        self.update_status_message("Stopping assistant...")
        self.toggle_button.configure(state="disabled", text="Stopping...")

        self.should_heartbeat = False

        # Stop lobby verification service
        stop_lobby_service()
        logger.info("Lobby verification service stopped")

        # Stop the tunnel using TunnelManager
        try:
            logger.info("Stopping tunnel...")
            self.tunnel_manager.stop_tunnel()
            logger.info("Tunnel stopped")
        except Exception as e:
            logger.error(f"Error stopping tunnel: {e}")

        logger.info("Server will continue running (restart required to stop)")

        self.reset_agent_state()
        self.update_status_message("The assistant is off.")

    def reset_agent_state(self):
        self.agent_running = False
        self.toggle_button.configure(state="normal")
        self.update_status_display(False)

    def logout(self):
        if self.agent_running:
            response = messagebox.askyesno(
                "Log Out",
                "The assistant is active. Do you want to stop it and log out?",
            )
            if response:
                self.stop_agent()
            else:
                return

        self.doctor_data = None
        self.show_login_screen()

    def on_closing(self):
        if self.agent_running:
            response = messagebox.askyesno(
                "Exit", "The assistant is active. Do you want to stop it and exit?"
            )
            if response:
                self.stop_agent()
                # Give time for tunnel to stop
                time.sleep(1)
                self.destroy()
        else:
            # Ensure tunnel is stopped even if agent_running is False
            try:
                self.tunnel_manager.stop_tunnel()
            except Exception as e:
                logger.error(f"Error stopping tunnel on close: {e}")
            self.destroy()


def main():
    app = RPAApplication()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
