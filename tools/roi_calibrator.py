"""
ROI Calibrator - Draw rectangles on an image to get coordinates.

Usage:
    python roi_calibrator.py                     # Capture current screen
    python roi_calibrator.py image.png           # Use specific image

Instructions:
    1. Run the script (with or without image)
    2. Draw rectangles with the mouse (click + drag)
    3. Use scrollbars or mouse wheel to navigate large images
    4. Rectangles remain visible
    5. Coordinates are printed to console (100% accurate)
    6. Copy to rpa_config.json

Note: The image is always displayed at 100% for maximum precision.
      If larger than the screen, use scroll to navigate.
"""

import sys
import tkinter as tk
from PIL import Image, ImageGrab, ImageTk


class ROICalibrator:
    def __init__(self, image_path: str = None):
        self.root = tk.Tk()
        self.root.title("ROI Calibrator - Draw regions")

        # Load image from file or capture screen
        if image_path:
            try:
                self.screenshot = Image.open(image_path)
                print(f"📷 Image loaded: {image_path}")
            except Exception as e:
                print(f"❌ Error loading image: {e}")
                print("   Using screen capture...")
                self.screenshot = ImageGrab.grab()
        else:
            self.screenshot = ImageGrab.grab()
            print("📷 Using current screen capture")

        self.img_width = self.screenshot.width
        self.img_height = self.screenshot.height
        print(f"   Size: {self.img_width} x {self.img_height}")

        # Calculate window size (maximum 90% of screen)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        max_win_width = int(screen_width * 0.90)
        max_win_height = int(screen_height * 0.85)  # Leave space for labels

        # Determine if scroll is needed
        self.needs_scroll = (
            self.img_width > max_win_width or self.img_height > max_win_height
        )

        # Viewport size (visible canvas area)
        viewport_width = min(self.img_width, max_win_width)
        viewport_height = min(self.img_height, max_win_height - 80)  # Space for labels

        if self.needs_scroll:
            print(f"   📜 Large image - scroll enabled")
            print(f"   Viewport: {viewport_width} x {viewport_height}")

        # Frame to contain canvas and scrollbars
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars
        self.h_scrollbar = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        self.v_scrollbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)

        # Canvas with scrollbars - viewport size, scrollregion of image size
        self.canvas = tk.Canvas(
            self.canvas_frame,
            width=viewport_width,
            height=viewport_height,
            xscrollcommand=self.h_scrollbar.set,
            yscrollcommand=self.v_scrollbar.set,
            scrollregion=(0, 0, self.img_width, self.img_height),
        )

        # Configure scrollbars
        self.h_scrollbar.config(command=self.canvas.xview)
        self.v_scrollbar.config(command=self.canvas.yview)

        # Layout with grid
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")

        # Make canvas expandable
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        # Display screenshot at 100%
        self.photo = ImageTk.PhotoImage(self.screenshot)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Variables for drawing
        self.start_x = None
        self.start_y = None
        self.current_rect = None  # Rectangle being drawn
        self.saved_rects = []  # Saved rectangles (permanent)
        self.saved_texts = []  # Rectangle texts
        self.region_count = 0  # Region counter

        # Bindings for drawing
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # Bindings for mouse wheel scroll
        self.canvas.bind("<MouseWheel>", self.on_mousewheel_y)  # Windows
        self.canvas.bind(
            "<Shift-MouseWheel>", self.on_mousewheel_x
        )  # Shift+Wheel for horizontal

        # Keyboard bindings
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<c>", self.clear_all)
        self.root.bind("<C>", self.clear_all)
        self.root.bind("<z>", self.undo_last)
        self.root.bind("<Z>", self.undo_last)

        # Instructions label
        scroll_info = " | Scroll: Mouse wheel" if self.needs_scroll else ""
        self.label = tk.Label(
            self.root,
            text=f"🖱️ Draw rectangles | C = Clear | Z = Undo | ESC = Exit{scroll_info}",
            font=("Arial", 11),
            bg="yellow",
        )
        self.label.pack(fill=tk.X)

        # Label to show coordinates
        self.coords_label = tk.Label(
            self.root, text="", font=("Consolas", 10), justify=tk.LEFT, anchor="w"
        )
        self.coords_label.pack(fill=tk.X, padx=10)

        print("\n" + "=" * 60)
        print("ROI CALIBRATOR")
        print("=" * 60)
        print("Controls:")
        print("  - Click + drag     → Draw region")
        print("  - C                → Clear all")
        print("  - Z                → Undo last")
        print("  - ESC              → Exit")
        if self.needs_scroll:
            print("-" * 60)
            print("  - Mouse wheel      → Vertical scroll")
            print("  - Shift + Wheel    → Horizontal scroll")
        print("=" * 60)
        print("📍 100% accurate coordinates (unscaled image)")
        print("=" * 60 + "\n")

    def on_mousewheel_y(self, event):
        """Vertical scroll with mouse wheel."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_mousewheel_x(self, event):
        """Horizontal scroll with Shift + mouse wheel."""
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _canvas_coords(self, event):
        """Convert event coordinates to real canvas (image) coordinates."""
        # canvasx/canvasy convert window coordinates to canvas coordinates
        return int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y))

    def on_press(self, event):
        self.start_x, self.start_y = self._canvas_coords(event)

    def on_drag(self, event):
        # Delete previous temporary rectangle
        if self.current_rect:
            self.canvas.delete(self.current_rect)

        # Get real canvas coordinates
        curr_x, curr_y = self._canvas_coords(event)

        # Draw new temporary rectangle (while dragging)
        self.current_rect = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            curr_x,
            curr_y,
            outline="red",
            width=2,
            dash=(4, 2),  # Dashed line while dragging
        )

    def on_release(self, event):
        # Delete temporary rectangle
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None

        # Get real canvas coordinates
        end_x, end_y = self._canvas_coords(event)

        # Calculate normalized coordinates (x1 < x2, y1 < y2)
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        w = x2 - x1
        h = y2 - y1

        if w < 10 or h < 10:
            return  # Ignore clicks without drag

        self.region_count += 1

        # Create PERMANENT rectangle (solid line)
        rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2)
        self.saved_rects.append(rect)

        # Add label with number and dimensions
        label_text = f"#{self.region_count} ({w}x{h})"
        text = self.canvas.create_text(
            x1 + 5,
            y1 + 5,
            text=label_text,
            anchor=tk.NW,
            fill="white",
            font=("Arial", 10, "bold"),
        )
        # Background for text
        bbox = self.canvas.bbox(text)
        bg = self.canvas.create_rectangle(bbox, fill="red", outline="red")
        self.canvas.tag_raise(text, bg)

        self.saved_texts.append(text)
        self.saved_texts.append(bg)

        # JSON format for rpa_config.json
        json_output = f'"region_{self.region_count}": {{ "x": {x1}, "y": {y1}, "w": {w}, "h": {h} }}'

        # Show in console
        print(f"\n📍 Region #{self.region_count}:")
        print(f"   Position: ({x1}, {y1}) → ({x2}, {y2})")
        print(f"   Size: {w} x {h}")
        print(f"\n   {json_output}")

        # Show in label
        self.coords_label.config(text=json_output)

    def undo_last(self, event=None):
        """Undo the last rectangle."""
        if self.saved_rects:
            # Delete last rectangle
            rect = self.saved_rects.pop()
            self.canvas.delete(rect)

            # Delete associated texts (text + background)
            if len(self.saved_texts) >= 2:
                self.canvas.delete(self.saved_texts.pop())
                self.canvas.delete(self.saved_texts.pop())

            self.region_count -= 1
            print(f"\n↩️ Undone region #{self.region_count + 1}")
            self.coords_label.config(text="")

    def clear_all(self, event=None):
        """Clear all rectangles."""
        for rect in self.saved_rects:
            self.canvas.delete(rect)
        for text in self.saved_texts:
            self.canvas.delete(text)

        self.saved_rects.clear()
        self.saved_texts.clear()
        self.region_count = 0
        self.coords_label.config(text="")
        print("\n🧹 All cleared")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Get image from argument if provided
    image_path = sys.argv[1] if len(sys.argv) > 1 else None

    calibrator = ROICalibrator(image_path)
    calibrator.run()
