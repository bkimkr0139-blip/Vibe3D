# Vibe3D Unity Accelerator — Windows Start Script
# Usage: .\scripts\start_all_windows.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vibe3dDir = Split-Path -Parent $ScriptDir
$ProjectDir = Split-Path -Parent $Vibe3dDir

Write-Host "=== Vibe3D Unity Accelerator ===" -ForegroundColor Cyan
Write-Host ""

# Load .env if exists
$envFile = Join-Path $Vibe3dDir ".env"
if (Test-Path $envFile) {
    Write-Host "[1/3] Loading .env..." -ForegroundColor Yellow
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
} else {
    Write-Host "[1/3] No .env file found, using defaults" -ForegroundColor Yellow
    Write-Host "       Copy .env.example to .env to customize" -ForegroundColor DarkGray
}

# Check MCP Server
Write-Host "[2/3] Checking MCP Server..." -ForegroundColor Yellow
$mcpUrl = if ($env:MCP_SERVER_URL) { $env:MCP_SERVER_URL } else { "http://localhost:8080/mcp" }
try {
    $response = Invoke-WebRequest -Uri $mcpUrl -Method POST -ContentType "application/json" -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"vibe3d-check","version":"1.0"}}}' -TimeoutSec 5 -ErrorAction Stop
    Write-Host "       MCP Server: ONLINE ($mcpUrl)" -ForegroundColor Green
} catch {
    Write-Host "       MCP Server: OFFLINE ($mcpUrl)" -ForegroundColor Red
    Write-Host "       Make sure Unity is running with MCP-FOR-UNITY package" -ForegroundColor DarkGray
    Write-Host ""
}

# Start Vibe3D Backend
Write-Host "[3/3] Starting Vibe3D Backend..." -ForegroundColor Yellow
$host_ = if ($env:VIBE3D_HOST) { $env:VIBE3D_HOST } else { "127.0.0.1" }
$port = if ($env:VIBE3D_PORT) { $env:VIBE3D_PORT } else { "8091" }

Write-Host ""
Write-Host "  Web UI:  http://${host_}:${port}" -ForegroundColor Cyan
Write-Host "  API:     http://${host_}:${port}/docs" -ForegroundColor Cyan
Write-Host "  MCP:     $mcpUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

Set-Location $ProjectDir
python -m uvicorn vibe3d.backend.main:app --host $host_ --port $port --reload
