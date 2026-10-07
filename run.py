"""
run.py
------
Unified concurrent launcher for the ProofLens Web Application.
Launches BOTH the FastAPI Backend and the Vite React Frontend simultaneously in one command.
Handles graceful shutdown of both services on Ctrl+C.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Automatically delegate to project .venv python if running from global python
_script_dir = Path(__file__).resolve().parent
_venv_python_win = _script_dir / ".venv" / "Scripts" / "python.exe"
_venv_python_posix = _script_dir / ".venv" / "bin" / "python"
_target_python = _venv_python_win if _venv_python_win.exists() else (_venv_python_posix if _venv_python_posix.exists() else None)

if _target_python and Path(sys.executable).resolve() != _target_python.resolve():
    try:
        import uvicorn
    except ImportError:
        sys.exit(subprocess.call([str(_target_python)] + sys.argv))

import uvicorn

# Configure stdout for Unicode compatibility on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BANNER = r"""
========================================================================
     ____                     __    __                     
    / __ \_________  ____  __/ /   / /__  ____  _____     
   / /_/ / ___/ __ \/ __ \/ /_/ /   / _ \/ __ \/ ___/     
  / ____/ /  / /_/ / /_/ / __/ /___/  __/ / / (__  )      
 /_/   /_/   \____/\____/_/ /_____/\___/_/ /_/____/       
                                                          
 Repair-Aware Proof-Carrying Data Analyst -- Unified Launcher     
========================================================================
 CORE LAW:
   LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.
   NO PROOF = NO NUMBER.
========================================================================
 [*] SERVICES RUNNING CONCURRENTLY:
   --> Frontend (Vite React HMR):     http://localhost:5173
   --> Backend (FastAPI Engine):       http://127.0.0.1:8000
   --> API Interactive Documentation: http://127.0.0.1:8000/docs
========================================================================
 Press Ctrl+C in this terminal to stop both services cleanly.
========================================================================
"""

frontend_proc = None


def kill_frontend():
    global frontend_proc
    if frontend_proc is not None:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(frontend_proc.pid)],
                    capture_output=True,
                )
            else:
                frontend_proc.terminate()
                frontend_proc.wait(timeout=3)
        except Exception:
            try:
                frontend_proc.kill()
            except Exception:
                pass
        frontend_proc = None


def main():
    global frontend_proc
    print(BANNER)

    frontend_dir = Path("frontend")
    has_frontend = frontend_dir.exists() and (frontend_dir / "package.json").exists()

    if has_frontend:
        try:
            print("  [*] Starting Vite React frontend (port 5173)...")
            cmd = ["cmd.exe", "/c", "npm run dev"] if sys.platform == "win32" else ["npm", "run", "dev"]
            frontend_proc = subprocess.Popen(
                cmd,
                cwd=str(frontend_dir),
            )
            time.sleep(1.5)  # Give Vite time to bind
        except Exception as e:
            print(f"  [!] Could not launch Vite frontend: {e}")
            print("  Falling back to FastAPI serving built frontend bundle.")

    def signal_handler(sig, frame):
        print("\n  [!] Shutting down backend and frontend...")
        kill_frontend()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        print("  [*] Starting FastAPI verification engine (port 8000)...\n")
        uvicorn.run("app.api.server:app", host="127.0.0.1", port=8000, reload=True)
    finally:
        kill_frontend()


if __name__ == "__main__":
    main()
