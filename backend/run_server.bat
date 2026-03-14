@echo off
setlocal EnableDelayedExpansion

:: ── SENTINEL — FastAPI Dev Server ─────────────────────────────────────────────
:: Run from: D:\Hackanova\backend\
:: Requires: Redis running on localhost:6379
::           PostgreSQL running on localhost:5432 (database: netrika)
::
:: Usage:
::   run_server.bat           — start on port 8000 (default)
::   run_server.bat 8080      — start on custom port

set "SCRIPT_DIR=%~dp0"
set "PORT=%1"
if "%PORT%"=="" set "PORT=8000"

:: Locate Python (prefer venv)
if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"
    echo [INFO] Using venv: %SCRIPT_DIR%venv
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"
    echo [INFO] Using venv: %SCRIPT_DIR%.venv
) else (
    set "PYTHON=python"
    echo [WARN] No venv found — using system Python
)

echo.
echo ============================================================
echo   SENTINEL FastAPI Server   (port %PORT%)
echo ============================================================
echo   Docs:   http://localhost:%PORT%/docs
echo   Health: http://localhost:%PORT%/health
echo   WS:     ws://localhost:%PORT%/ws/vitals/{patient_id}
echo ============================================================
echo.

:: Load .env is handled by conftest / python-dotenv in main.py startup
:: Make sure .env exists
if not exist "%SCRIPT_DIR%.env" (
    echo [WARN] .env not found — copying from .env.example
    copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" >nul 2>&1
)

:: Install dependencies (fast — pip skips if already installed)
echo [INFO] Syncing dependencies...
"%PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt" -q
if errorlevel 1 (
    echo [ERROR] pip install failed. Aborting.
    exit /b 1
)

echo [INFO] Starting uvicorn on port %PORT% with --reload
echo.

"%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload --log-level info

exit /b !errorlevel!
