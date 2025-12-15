# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui.py', 'app.py'],  # Include app.py in analysis for proper import
    pathex=[],
    binaries=[
        ('bin/cloudflared.exe', 'bin'),  # Incluir cloudflared
    ],
    datas=[
        ('config.py', '.'),
        ('logger.py', '.'),
        ('config_manager.py', '.'),
        ('tunnel_manager.py', '.'),
        ('.env', '.'),  # ⭐ Archivo de variables de entorno
        ('rpa_config.json', '.'),  # ⭐ Configuración centralizada
        ('images', 'images'),  # ⭐ Todas las imágenes para PyAutoGUI
        # ⭐ New modules
        ('core', 'core'),
        ('flows', 'flows'),
        ('api', 'api'),
        ('services', 'services'),
    ],
    hiddenimports=[
        'customtkinter',
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'requests',
        'pydantic',
        'starlette',
        'pyautogui',  # Required by app.py
        'pydirectinput',  # DirectInput for VDI keyboard/mouse
        'pyperclip',  # Clipboard operations
        'boto3',  # Required by app.py
        'botocore',  # Required by boto3
        'logging',  # VDI logging
        'pathlib',  # Path handling
        # ⭐ New modules as hidden imports
        'core',
        'core.rpa_engine',
        'core.system_utils',
        'core.vdi_input',
        'core.s3_client',
        'flows',
        'flows.base_flow',
        'flows.baptist',
        'flows.jackson',
        'flows.steward',
        'api',
        'api.models',
        'api.routes',
        'services',
        'services.auth_service',
        'services.agent_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='HannaMedRPA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Sin ventana de consola
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
