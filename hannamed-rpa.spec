# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata
import sys
sys.setrecursionlimit(sys.getrecursionlimit() * 5)

block_cipher = None

# Collect metadata for packages that use importlib.metadata.version()
replicate_metadata = copy_metadata('replicate')
httpx_metadata = copy_metadata('httpx')
langchain_metadata = copy_metadata('langchain')
langchain_core_metadata = copy_metadata('langchain_core')
langchain_google_genai_metadata = copy_metadata('langchain_google_genai')
langchain_community_metadata = copy_metadata('langchain_community')
langchain_text_splitters_metadata = copy_metadata('langchain_text_splitters')
# langchain-google-genai v4.x uses google-genai SDK
google_genai_metadata = copy_metadata('google-genai')

a = Analysis(
    ['gui.py', 'app.py'],  # Include app.py in analysis for proper import
    pathex=[],
    binaries=[
        ('bin/cloudflared.exe', 'bin'),  # Include cloudflared
    ],
    datas=[
        ('config.py', '.'),
        ('logger.py', '.'),
        ('config_manager.py', '.'),
        ('tunnel_manager.py', '.'),
        ('.env', '.'),  # Environment variables file
        ('rpa_config.json', '.'),  # Centralized configuration
        ('images', 'images'),  # All images for PyAutoGUI
        # New modules
        ('core', 'core'),
        ('flows', 'flows'),
        ('api', 'api'),
        ('services', 'services'),
        ('agentic', 'agentic'),  # Agentic module for RPA automation
    ] + replicate_metadata + httpx_metadata + langchain_metadata + langchain_core_metadata + langchain_google_genai_metadata + langchain_community_metadata + langchain_text_splitters_metadata + google_genai_metadata,
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
        # Replicate for OmniParser (agentic)
        'replicate',
        'replicate.client',
        'replicate.__about__',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'httpcore',
        # Agentic module
        'agentic',
        'agentic.agent_runner',
        'agentic.action_executor',
        'agentic.omniparser_client',
        'agentic.screen_capturer',
        'agentic.models',
        # New Agentic submodules
        'agentic.core',
        'agentic.core.base_agent',
        'agentic.core.llm',
        'agentic.emr',
        'agentic.emr.jackson',
        'agentic.emr.jackson.patient_finder',
        'agentic.emr.jackson.report_finder',
        'agentic.emr.jackson.tools',
        'agentic.runners',
        'agentic.runners.jackson_summary_runner',
        # External AI dependencies - langchain_core (actual modules that exist in v1.2.x)
        'langchain',
        'langchain_core',
        'langchain_core.messages',
        'langchain_core.messages.base',
        'langchain_core.messages.human',
        'langchain_core.messages.ai',
        'langchain_core.messages.system',
        'langchain_core.outputs',
        'langchain_core.output_parsers',
        'langchain_core.language_models',
        'langchain_core.language_models.base',
        'langchain_core.language_models.chat_models',
        'langchain_core.load',
        'langchain_core.load.serializable',
        'langchain_core.runnables',
        'langchain_core.runnables.base',
        'langchain_core.callbacks',
        'langchain_core.callbacks.manager',
        # langchain_google_genai v4.x
        'langchain_google_genai',
        'langchain_google_genai.chat_models',
        # langchain_community and text splitters
        'langchain_community',
        'langchain_text_splitters',
        # google-genai SDK (new for v4.x)
        'google.genai',
        'google.genai.types',
        'google.genai.client',
        # Core modules
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
    # OPTIMIZATION: Exclude heavy packages not used by the application
    # These are optional dependencies of langchain-community that add HUGE build time
    excludes=[
        # Data science packages (NOT needed for RPA)
        'pandas',
        'scipy',
        'sklearn',
        'scikit-learn',
        'matplotlib',
        'matplotlib.pyplot',
        'nltk',
        'pyarrow',
        'sympy',
        # Database drivers (NOT needed)
        'psycopg2',
        'MySQLdb',
        'pysqlite2',
        'pymysql',
        # Testing (NOT needed in production)
        'pytest',
        'unittest',
        # Jupyter/IPython (NOT needed)
        'IPython',
        'jupyter',
        'notebook',
        # Other heavy optional deps
        'tensorflow',
        'torch',
        'transformers',
        'faiss',
        'chromadb',
        # Legacy google.generativeai (deprecated, using google.genai instead)
        'google.generativeai',
        'google.ai.generativelanguage',
    ],
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
    console=False,  # No console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
