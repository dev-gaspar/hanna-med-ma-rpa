"""
ROI Calibrator - Dibuja rectángulos en una imagen para obtener coordenadas.

Uso:
    python roi_calibrator.py                     # Captura pantalla actual
    python roi_calibrator.py imagen.png          # Usa imagen específica

Instrucciones:
    1. Ejecutar el script (con o sin imagen)
    2. Dibujar rectángulos con el mouse (click + arrastrar)
    3. Usar scrollbars o rueda del mouse para navegar imágenes grandes
    4. Los rectángulos permanecen visibles
    5. Las coordenadas se imprimen en la consola (100% precisas)
    6. Copiar al rpa_config.json

Nota: La imagen siempre se muestra al 100% para máxima precisión.
      Si es más grande que la pantalla, usa scroll para navegar.
"""

import sys
import tkinter as tk
from PIL import Image, ImageGrab, ImageTk


class ROICalibrator:
    def __init__(self, image_path: str = None):
        self.root = tk.Tk()
        self.root.title("ROI Calibrator - Dibuja regiones")

        # Cargar imagen desde archivo o capturar pantalla
        if image_path:
            try:
                self.screenshot = Image.open(image_path)
                print(f"📷 Imagen cargada: {image_path}")
            except Exception as e:
                print(f"❌ Error cargando imagen: {e}")
                print("   Usando captura de pantalla...")
                self.screenshot = ImageGrab.grab()
        else:
            self.screenshot = ImageGrab.grab()
            print("📷 Usando captura de pantalla actual")

        self.img_width = self.screenshot.width
        self.img_height = self.screenshot.height
        print(f"   Tamaño: {self.img_width} x {self.img_height}")

        # Calcular tamaño de ventana (máximo 90% de pantalla)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        max_win_width = int(screen_width * 0.90)
        max_win_height = int(screen_height * 0.85)  # Dejar espacio para labels

        # Determinar si necesitamos scroll
        self.needs_scroll = (
            self.img_width > max_win_width or self.img_height > max_win_height
        )

        # Tamaño del viewport (área visible del canvas)
        viewport_width = min(self.img_width, max_win_width)
        viewport_height = min(
            self.img_height, max_win_height - 80
        )  # Espacio para labels

        if self.needs_scroll:
            print(f"   📜 Imagen grande - scroll habilitado")
            print(f"   Viewport: {viewport_width} x {viewport_height}")

        # Frame para contener canvas y scrollbars
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars
        self.h_scrollbar = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        self.v_scrollbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)

        # Canvas con scrollbars - tamaño del viewport, scrollregion del tamaño de imagen
        self.canvas = tk.Canvas(
            self.canvas_frame,
            width=viewport_width,
            height=viewport_height,
            xscrollcommand=self.h_scrollbar.set,
            yscrollcommand=self.v_scrollbar.set,
            scrollregion=(0, 0, self.img_width, self.img_height),
        )

        # Configurar scrollbars
        self.h_scrollbar.config(command=self.canvas.xview)
        self.v_scrollbar.config(command=self.canvas.yview)

        # Layout con grid
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")

        # Hacer que el canvas se expanda
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        # Mostrar screenshot al 100%
        self.photo = ImageTk.PhotoImage(self.screenshot)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Variables para dibujar
        self.start_x = None
        self.start_y = None
        self.current_rect = None  # Rectángulo siendo dibujado
        self.saved_rects = []  # Rectángulos guardados (permanentes)
        self.saved_texts = []  # Textos de los rectángulos
        self.region_count = 0  # Contador de regiones

        # Bindings para dibujar
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # Bindings para scroll con rueda del mouse
        self.canvas.bind("<MouseWheel>", self.on_mousewheel_y)  # Windows
        self.canvas.bind(
            "<Shift-MouseWheel>", self.on_mousewheel_x
        )  # Shift+Wheel para horizontal

        # Bindings de teclado
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<c>", self.clear_all)
        self.root.bind("<C>", self.clear_all)
        self.root.bind("<z>", self.undo_last)
        self.root.bind("<Z>", self.undo_last)

        # Label de instrucciones
        scroll_info = " | Scroll: Rueda mouse" if self.needs_scroll else ""
        self.label = tk.Label(
            self.root,
            text=f"🖱️ Dibuja rectángulos | C = Limpiar | Z = Deshacer | ESC = Salir{scroll_info}",
            font=("Arial", 11),
            bg="yellow",
        )
        self.label.pack(fill=tk.X)

        # Label para mostrar coordenadas
        self.coords_label = tk.Label(
            self.root, text="", font=("Consolas", 10), justify=tk.LEFT, anchor="w"
        )
        self.coords_label.pack(fill=tk.X, padx=10)

        print("\n" + "=" * 60)
        print("ROI CALIBRATOR")
        print("=" * 60)
        print("Controles:")
        print("  - Click + arrastrar → Dibujar región")
        print("  - C                 → Limpiar todo")
        print("  - Z                 → Deshacer último")
        print("  - ESC               → Salir")
        if self.needs_scroll:
            print("-" * 60)
            print("  - Rueda mouse       → Scroll vertical")
            print("  - Shift + Rueda     → Scroll horizontal")
        print("=" * 60)
        print("📍 Coordenadas 100% precisas (imagen sin escalar)")
        print("=" * 60 + "\n")

    def on_mousewheel_y(self, event):
        """Scroll vertical con rueda del mouse."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_mousewheel_x(self, event):
        """Scroll horizontal con Shift + rueda del mouse."""
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _canvas_coords(self, event):
        """Convierte coordenadas del evento a coordenadas reales del canvas (imagen)."""
        # canvasx/canvasy convierten coordenadas de ventana a coordenadas de canvas
        return int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y))

    def on_press(self, event):
        self.start_x, self.start_y = self._canvas_coords(event)

    def on_drag(self, event):
        # Eliminar rectángulo temporal anterior
        if self.current_rect:
            self.canvas.delete(self.current_rect)

        # Obtener coordenadas reales del canvas
        curr_x, curr_y = self._canvas_coords(event)

        # Dibujar nuevo rectángulo temporal (mientras se arrastra)
        self.current_rect = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            curr_x,
            curr_y,
            outline="red",
            width=2,
            dash=(4, 2),  # Línea punteada mientras arrastra
        )

    def on_release(self, event):
        # Eliminar rectángulo temporal
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None

        # Obtener coordenadas reales del canvas
        end_x, end_y = self._canvas_coords(event)

        # Calcular coordenadas normalizadas (x1 < x2, y1 < y2)
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        w = x2 - x1
        h = y2 - y1

        if w < 10 or h < 10:
            return  # Ignorar clicks sin arrastre

        self.region_count += 1

        # Crear rectángulo PERMANENTE (línea sólida)
        rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2)
        self.saved_rects.append(rect)

        # Agregar etiqueta con número y dimensiones
        label_text = f"#{self.region_count} ({w}x{h})"
        text = self.canvas.create_text(
            x1 + 5,
            y1 + 5,
            text=label_text,
            anchor=tk.NW,
            fill="white",
            font=("Arial", 10, "bold"),
        )
        # Fondo para el texto
        bbox = self.canvas.bbox(text)
        bg = self.canvas.create_rectangle(bbox, fill="red", outline="red")
        self.canvas.tag_raise(text, bg)

        self.saved_texts.append(text)
        self.saved_texts.append(bg)

        # Formato JSON para rpa_config.json
        json_output = f'"region_{self.region_count}": {{ "x": {x1}, "y": {y1}, "w": {w}, "h": {h} }}'

        # Mostrar en consola
        print(f"\n📍 Región #{self.region_count}:")
        print(f"   Posición: ({x1}, {y1}) → ({x2}, {y2})")
        print(f"   Tamaño: {w} x {h}")
        print(f"\n   {json_output}")

        # Mostrar en label
        self.coords_label.config(text=json_output)

    def undo_last(self, event=None):
        """Deshacer el último rectángulo."""
        if self.saved_rects:
            # Eliminar último rectángulo
            rect = self.saved_rects.pop()
            self.canvas.delete(rect)

            # Eliminar textos asociados (texto + fondo)
            if len(self.saved_texts) >= 2:
                self.canvas.delete(self.saved_texts.pop())
                self.canvas.delete(self.saved_texts.pop())

            self.region_count -= 1
            print(f"\n↩️ Deshecho región #{self.region_count + 1}")
            self.coords_label.config(text="")

    def clear_all(self, event=None):
        """Limpiar todos los rectángulos."""
        for rect in self.saved_rects:
            self.canvas.delete(rect)
        for text in self.saved_texts:
            self.canvas.delete(text)

        self.saved_rects.clear()
        self.saved_texts.clear()
        self.region_count = 0
        self.coords_label.config(text="")
        print("\n🧹 Todo limpiado")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Obtener imagen de argumento si se proporciona
    image_path = sys.argv[1] if len(sys.argv) > 1 else None

    calibrator = ROICalibrator(image_path)
    calibrator.run()
