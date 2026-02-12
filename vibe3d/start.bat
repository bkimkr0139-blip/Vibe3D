@echo off
title Vibe3D Unity Accelerator
color 0A

echo.
echo   ========================================
echo     Vibe3D Unity Accelerator
echo   ========================================
echo.

:: Check if already running
netstat -ano 2>nul | findstr ":8091.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   Server already running!
    echo   Opening browser...
    start http://127.0.0.1:8091/
    timeout /t 3 >nul
    exit /b 0
)

:: Change to project root (parent of vibe3d/)
cd /d "%~dp0.."

echo   Starting server on http://127.0.0.1:8091/
echo   Press Ctrl+C to stop
echo.

:: Open browser after 3 seconds (background)
start /b cmd /c "timeout /t 3 >nul && start http://127.0.0.1:8091/"

:: Start uvicorn
python -m uvicorn vibe3d.backend.main:app --host 127.0.0.1 --port 8091

:: If server stopped or failed
echo.
echo   Server stopped.
pause
