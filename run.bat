@echo off
REM ProofLens Launcher for Windows
REM Automatically uses the project virtual environment
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py %*
) else (
    python run.py %*
)
