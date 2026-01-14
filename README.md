# Hanna-Med RPA Agent

Robotic Process Automation (RPA) agent for obtaining medical credentials in EMR systems of Florida hospitals.

## Description

This RPA automates the login, navigation, and information capture process in credential portals of three hospitals:

- **Baptist Health South Florida**
- **Jackson Health System**
- **Steward Health Care**

## Requirements

- Python 3.10+
- VDI access to hospital systems
- AWS S3 credentials (for screenshot storage)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

The agent runs as a FastAPI service that receives webhooks from n8n:

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

It also includes a graphical user interface (GUI) for monitoring:

```bash
python gui.py
```

## Structure

```
├── api/          # FastAPI endpoints
├── core/         # Base RPA engine
├── flows/        # Hospital-specific flows (baptist, jackson, steward)
├── services/     # Auxiliary services
└── images/       # Reference images for detection
```

## Configuration

Settings are managed in `rpa_config.json` and environment variables in `.env`.
