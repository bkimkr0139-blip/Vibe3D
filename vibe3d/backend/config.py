"""Vibe3D configuration."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).parent.parent

# Load .env from project root
load_dotenv(BASE_DIR / ".env")
ASSETS_DIR = BASE_DIR / "assets"
LOGS_DIR = BASE_DIR / "logs"
SCHEMA_DIR = BASE_DIR / "docs" / "schemas"
FRONTEND_DIR = BASE_DIR / "frontend"

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
