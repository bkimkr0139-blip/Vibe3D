"""Vibe3D configuration."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ── Base directory (frozen vs development) ────────────────────
# PyInstaller onedir: sys._MEIPASS points to the bundle root
# run.py sets VIBE3D_BASE_DIR before importing this module
_env_base = os.environ.get("VIBE3D_BASE_DIR")
if _env_base:
    BASE_DIR = Path(_env_base)
elif getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS) / "vibe3d"
else:
    BASE_DIR = Path(__file__).parent.parent

# ── .env loading ──────────────────────────────────────────────
# 1) Bundle-internal .env (for defaults baked into the package)
load_dotenv(BASE_DIR / ".env")
# 2) Exe-adjacent .env (user-editable overrides, frozen mode only)
_exe_dir = os.environ.get("VIBE3D_EXE_DIR")
if _exe_dir:
    _exe_env = Path(_exe_dir) / ".env"
    if _exe_env.is_file():
        load_dotenv(_exe_env, override=True)

# Paths
ASSETS_DIR = BASE_DIR / "assets"
SCHEMA_DIR = BASE_DIR / "docs" / "schemas"
FRONTEND_DIR = BASE_DIR / "frontend"

# Logs go next to the exe (writable) in frozen mode, else under BASE_DIR
if _exe_dir:
    LOGS_DIR = Path(_exe_dir) / "logs"
else:
    LOGS_DIR = BASE_DIR / "logs"

# MCP Server
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8080/mcp")
MCP_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "60"))

# LLM (Claude API) — optional, for natural language → plan conversion
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

# Server
HOST = os.environ.get("VIBE3D_HOST", "127.0.0.1")
PORT = int(os.environ.get("VIBE3D_PORT", "8091"))

# Unity
UNITY_PROJECT_PATH = os.environ.get(
    "UNITY_PROJECT_PATH",
    r"C:\UnityProjects\My project",
)
DEFAULT_SCENE = os.environ.get("DEFAULT_SCENE", "bio-plants")
