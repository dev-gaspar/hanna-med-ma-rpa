# Hanna-Med RPA Agent

Agente de automatización robótica (RPA) para la obtención de credenciales médicas en sistemas EMR de hospitales de Florida.

## Descripción

Este RPA automatiza el proceso de login, navegación y captura de información en los portales de credenciales de tres hospitales:

- **Baptist Health South Florida**
- **Jackson Health System**
- **Steward Health Care**

## Requisitos

- Python 3.10+
- Acceso VDI a los sistemas hospitalarios
- Credenciales de AWS S3 (para almacenamiento de capturas)

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

El agente se ejecuta como un servicio FastAPI que recibe webhooks desde n8n:

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

También incluye una interfaz gráfica (GUI) para monitoreo:

```bash
python gui.py
```

## Estructura

```
├── api/          # Endpoints FastAPI
├── core/         # Motor RPA base
├── flows/        # Flujos por hospital (baptist, jackson, steward)
├── services/     # Servicios auxiliares
└── images/       # Imágenes de referencia para detección
```

## Configuración

Las configuraciones se manejan en `rpa_config.json` y variables de entorno en `.env`.
