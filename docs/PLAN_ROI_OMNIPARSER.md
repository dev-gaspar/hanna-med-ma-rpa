# ROI-Based Screen Capture para Agentes

## Problema

OmniParser procesa pantalla completa → 100+ elementos → ruido para Gemini → decisiones imprecisas.

## Solución

Enmascarar pantalla en blanco excepto las regiones de interés (ROI). OmniParser ignora el blanco.

```
ANTES:                              DESPUÉS:
┌──────────────────────┐           ┌──────────────────────┐
│ Menu │ Toolbar │ X   │           │████████████████████ │ ← BLANCO
├──────┴─────────┴─────┤           ├────────┬─────────────┤
│ Panel  │  Content    │    →      │ [ROI1] │ [ROI2]      │ ← VISIBLE
│ Left   │  Area       │           │        │             │
└────────┴─────────────┘           └────────┴─────────────┘
     100+ elementos                     20-30 elementos
```

**Ventaja:** Coordenadas ya son absolutas (imagen mismo tamaño que pantalla).

---

## Arquitectura

```
rpa_config.json
└── roi_definitions[emr][resolution][agent] → List[region_name]
└── roi_regions[emr][resolution][region_name] → {x, y, w, h}
                    │
                    ▼
ScreenCapturer.capture_with_mask(rois: List[ROI])
→ Pantalla completa con solo ROIs visibles, resto blanco
                    │
                    ▼
OmniParser.parse_image()
→ Detecta elementos solo en áreas visibles
→ Coordenadas absolutas (sin transformación)
```

---

## Configuración (rpa_config.json)

```json
{
	"roi_definitions": {
		"jackson": {
			"1366x768": {
				"patient_finder": ["patient_list"],
				"report_finder": ["notes_tree", "report_content"]
			}
		}
	},
	"roi_regions": {
		"jackson": {
			"1366x768": {
				"patient_list": { "x": 0, "y": 100, "w": 400, "h": 600 },
				"notes_tree": { "x": 0, "y": 50, "w": 350, "h": 600 },
				"report_content": { "x": 350, "y": 100, "w": 1016, "h": 600 }
			}
		}
	}
}
```

---

## Implementación

### 1. ROI Dataclass

```python
# agentic/models.py

@dataclass
class ROI:
    x: int
    y: int
    w: int
    h: int

    @property
    def bbox(self) -> tuple:
        return (self.x, self.y, self.x + self.w, self.y + self.h)
```

### 2. Captura con máscara

```python
# agentic/screen_capturer.py

def capture_with_mask(self, rois: List[ROI]) -> Image.Image:
    """Pantalla con solo ROIs visibles, resto blanco."""
    screenshot = self.capture()
    masked = Image.new("RGB", screenshot.size, (255, 255, 255))

    for roi in rois:
        masked.paste(screenshot.crop(roi.bbox), (roi.x, roi.y))

    return masked
```

### 3. Obtener ROIs de config

```python
# agentic/screen_capturer.py

def get_agent_rois(emr: str, agent: str) -> List[ROI]:
    resolution = get_current_resolution()

    try:
        names = config["roi_definitions"][emr][resolution][agent]
        regions = config["roi_regions"][emr][resolution]
        return [ROI(**regions[n]) for n in names if n in regions]
    except KeyError:
        return []
```

### 4. Uso

```python
# En cualquier Runner

rois = get_agent_rois("jackson", "report_finder")
screenshot = capturer.capture_with_mask(rois) if rois else capturer.capture()
parsed = omniparser.parse_image(screenshot)
```

---

## Escalabilidad

| Agregar...       | Qué hacer                                               |
| ---------------- | ------------------------------------------------------- |
| Nuevo agente     | `roi_definitions[emr][res]["new_agent"] = ["region_a"]` |
| Nueva región     | `roi_regions[emr][res]["region_a"] = {x, y, w, h}`      |
| Nueva resolución | Agregar key en `roi_definitions` y `roi_regions`        |
| Nuevo EMR        | Agregar key top-level en ambos                          |

---

## Fallback

Sin ROI configurado → pantalla completa (comportamiento actual).

---

## Archivos a modificar

1. `rpa_config.json` - Agregar configs
2. `agentic/models.py` - Agregar `ROI`
3. `agentic/screen_capturer.py` - Agregar `capture_with_mask()`, `get_agent_rois()`
4. Runners - Usar nuevo método

---

## Calibrador (opcional)

```python
"""roi_calibrator.py"""
import tkinter as tk
from PIL import ImageGrab, ImageTk

class Calibrator:
    def __init__(self):
        self.root = tk.Tk()
        self.img = ImageGrab.grab()
        self.canvas = tk.Canvas(self.root, width=self.img.width, height=self.img.height)
        self.canvas.pack()
        self.photo = ImageTk.PhotoImage(self.img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.start = self.rect = None
        self.canvas.bind("<Button-1>", lambda e: setattr(self, 'start', (e.x, e.y)))
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)

    def drag(self, e):
        if self.rect: self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(*self.start, e.x, e.y, outline="red", width=2)

    def release(self, e):
        x, y = min(self.start[0], e.x), min(self.start[1], e.y)
        print(f'"name": {{ "x": {x}, "y": {y}, "w": {abs(e.x-self.start[0])}, "h": {abs(e.y-self.start[1])} }}')

if __name__ == "__main__":
    c = Calibrator()
    c.root.mainloop()
```
