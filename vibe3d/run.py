"""Vibe3D Accelerator — Standalone entry point for PyInstaller exe.

Usage:
    python -m vibe3d.run          (development)
    Vibe3D.exe                    (packaged)
"""

import os
import sys
import webbrowser
import threading

# ── Frozen environment detection ─────────────────────────────
# PyInstaller sets sys._MEIPASS to the temp extraction directory (onefile)
# or the bundle directory (onedir). We use this to locate bundled data files.

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _setup_frozen_path():
    """Ensure bundled modules are importable in frozen (PyInstaller) builds.

    PyInstaller onedir puts everything under _MEIPASS. We need _MEIPASS on
    sys.path so that ``import vibe3d.backend.main`` resolves correctly even
    when the exe is launched from an arbitrary working directory.
    """
    if _is_frozen():
        bundle_root = sys._MEIPASS
        if bundle_root not in sys.path:
            sys.path.insert(0, bundle_root)


def _get_base_dir():
    """Return the base directory for bundled data files.

    In frozen mode, data files are under _MEIPASS/vibe3d/ (matching dev layout).
    In development, this is the vibe3d/ directory containing this file.
    """
    if _is_frozen():
        return os.path.join(sys._MEIPASS, "vibe3d")
    # Development: vibe3d/ is the directory containing this file
    return os.path.dirname(os.path.abspath(__file__))


def main():
    # Frozen module path fix — must run before any vibe3d imports
    _setup_frozen_path()

    # Ensure the vibe3d package can resolve its base directory
    os.environ["VIBE3D_BASE_DIR"] = _get_base_dir()

    # In frozen mode, .env lives next to the exe (not inside the bundle)
    if _is_frozen():
        exe_dir = os.path.dirname(sys.executable)
        os.environ["VIBE3D_EXE_DIR"] = exe_dir

        # Load .env from exe directory if it exists
        env_path = os.path.join(exe_dir, ".env")
        if os.path.isfile(env_path):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=True)
            except ImportError:
                pass

    # Import config after env vars are set
    from vibe3d.backend.config import HOST, PORT

    # Banner
    url = f"http://{HOST}:{PORT}"
    print("=" * 56)
    print("  Vibe3D Unity Accelerator")
    print(f"  Server: {url}")
    print(f"  Docs:   {url}/docs")
    print("=" * 56)
    print()

    # Auto-open browser after a short delay
    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    # Start uvicorn
    import uvicorn
    uvicorn.run(
        "vibe3d.backend.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print(f"[ERROR] {exc}")
        print()
        if _is_frozen():
            input("Press Enter to exit...")
