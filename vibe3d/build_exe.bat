@echo off
setlocal
title Vibe3D - Build EXE

echo ============================================================
echo   Vibe3D Unity Accelerator - Windows EXE Build
echo ============================================================
echo.

:: Change to vibe3d directory (where this script lives)
cd /d "%~dp0"

:: Step 1: Install dependencies
echo [1/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed
    pause
    exit /b 1
)
echo.

:: Step 2: Run PyInstaller
echo [2/4] Building with PyInstaller (onedir mode)...
pyinstaller --clean --noconfirm vibe3d.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)
echo.

:: Step 3: Copy .env.example as .env template + README next to exe
echo [3/4] Copying config and docs...
if not exist "dist\Vibe3D\.env" (
    copy ".env.example" "dist\Vibe3D\.env" >nul 2>&1
)
copy "README.md" "dist\Vibe3D\README.md" >nul 2>&1
echo.

:: Step 4: Create ZIP package
echo [4/4] Creating ZIP package...
if exist "dist\Vibe3D-win64.zip" del "dist\Vibe3D-win64.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Vibe3D' -DestinationPath 'dist\Vibe3D-win64.zip' -Force"
if errorlevel 1 (
    echo WARNING: ZIP creation failed (non-critical)
) else (
    echo   Created dist\Vibe3D-win64.zip
)
echo.

echo ============================================================
echo   Build complete!
echo   EXE:  %~dp0dist\Vibe3D\Vibe3D.exe
echo   ZIP:  %~dp0dist\Vibe3D-win64.zip
echo ============================================================
echo.
echo   To run: double-click dist\Vibe3D\Vibe3D.exe
echo   Edit dist\Vibe3D\.env to configure settings
echo.
pause
