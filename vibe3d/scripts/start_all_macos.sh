#!/bin/bash
# Vibe3D Unity Accelerator — macOS/Linux Start Script
# Usage: ./scripts/start_all_macos.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VIBE3D_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$VIBE3D_DIR")"

echo "=== Vibe3D Unity Accelerator ==="
echo ""

# Load .env if exists
ENV_FILE="$VIBE3D_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    echo "[1/3] Loading .env..."
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "[1/3] No .env file found, using defaults"
    echo "       Copy .env.example to .env to customize"
fi

# Check MCP Server
echo "[2/3] Checking MCP Server..."
MCP_URL="${MCP_SERVER_URL:-http://localhost:8080/mcp}"
if curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"vibe3d-check","version":"1.0"}}}' \
    --max-time 5 > /dev/null 2>&1; then
    echo "       MCP Server: ONLINE ($MCP_URL)"
else
    echo "       MCP Server: OFFLINE ($MCP_URL)"
    echo "       Make sure Unity is running with MCP-FOR-UNITY package"
fi

# Start Vibe3D Backend
echo "[3/3] Starting Vibe3D Backend..."
HOST="${VIBE3D_HOST:-127.0.0.1}"
PORT="${VIBE3D_PORT:-8091}"

echo ""
echo "  Web UI:  http://${HOST}:${PORT}"
echo "  API:     http://${HOST}:${PORT}/docs"
echo "  MCP:     $MCP_URL"
echo ""
echo "Press Ctrl+C to stop"
echo ""

cd "$PROJECT_DIR"
python -m uvicorn vibe3d.backend.main:app --host "$HOST" --port "$PORT" --reload
