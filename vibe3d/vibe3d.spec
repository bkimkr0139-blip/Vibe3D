# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Vibe3D Unity Accelerator.

Build:  pyinstaller vibe3d.spec
Output: dist/Vibe3D/Vibe3D.exe
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Paths relative to this spec file
SPEC_DIR = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    [os.path.join(SPEC_DIR, 'run.py')],
    pathex=[os.path.dirname(SPEC_DIR)],  # parent of vibe3d/ so "vibe3d.*" resolves
    binaries=[],
    datas=[
        # Frontend (HTML/JS/CSS)
        (os.path.join(SPEC_DIR, 'frontend'), os.path.join('vibe3d', 'frontend')),
        # Data files (workflows.json)
        (os.path.join(SPEC_DIR, 'data'), os.path.join('vibe3d', 'data')),
        # Docs (schemas, prompts)
        (os.path.join(SPEC_DIR, 'docs'), os.path.join('vibe3d', 'docs')),
        # .env.example as reference
        (os.path.join(SPEC_DIR, '.env.example'), 'vibe3d'),
        # README for distribution
        (os.path.join(SPEC_DIR, 'README.md'), '.'),
    ],
    hiddenimports=[
        # ── Vibe3D internal modules ──
        'vibe3d',
        'vibe3d.backend',
        'vibe3d.backend.config',
        'vibe3d.backend.main',
        'vibe3d.backend.executor',
        'vibe3d.backend.plan_validator',
        'vibe3d.backend.plan_generator',
        'vibe3d.backend.scene_cache',
        'vibe3d.backend.suggestion_engine',
        'vibe3d.backend.error_analyzer',
        'vibe3d.backend.source_analyzer',
        'vibe3d.backend.composite_analyzer',
        'vibe3d.backend.workflow_manager',
        'vibe3d.backend.nlu_engine',
        'vibe3d.backend.component_library',
        'vibe3d.backend.fermentation_bridge',
        'vibe3d.mcp_client',
        'vibe3d.mcp_client.client',

        # ── FastAPI / Starlette ──
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.responses',
        'fastapi.staticfiles',
        'starlette',
        'starlette.applications',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.routing',
        'starlette.responses',
        'starlette.staticfiles',
        'starlette.websockets',
        'starlette.requests',
        'starlette.datastructures',
        'starlette.status',
        'starlette.exceptions',

        # ── Uvicorn (server + protocol handlers) ──
        'uvicorn',
        'uvicorn.config',
        'uvicorn.main',
        'uvicorn.server',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',

        # ── Pydantic ──
        'pydantic',
        'pydantic.main',
        'pydantic.fields',
        'pydantic.json_schema',

        # ── HTTP / Network ──
        'h11',
        'httpcore',
        'httpx',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.server',
        'multipart',
        'multipart.multipart',

        # ── Async ──
        'anyio',
        'anyio._core',
        'anyio._backends',
        'anyio._backends._asyncio',
        'sniffio',

        # ── Other deps ──
        'jsonschema',
        'jsonschema.validators',
        'dotenv',
        'anthropic',
        'certifi',
        'idna',
        'charset_normalizer',
        'typing_extensions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'cv2',
        'pytest', 'unittest',
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
    [],
    exclude_binaries=True,
    name='Vibe3D',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for server logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Vibe3D',
)
