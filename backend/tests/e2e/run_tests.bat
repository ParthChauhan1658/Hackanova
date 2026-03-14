@echo off
setlocal EnableDelayedExpansion

:: ── SENTINEL — E2E Test Runner ──────────────────────────────────────────────
:: Run from: D:\Hackanova\backend\
:: Requires: FastAPI on :8000, Redis on :6379, PostgreSQL on :5432

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%..\.."

:: Locate Python (prefer venv)
if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
    echo [INFO] Using venv
) else if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
    echo [INFO] Using .venv
) else (
    set "PYTHON=python"
    echo [WARN] No venv found — using system Python
)

echo.
echo ═══════════════════════════════════════════════
echo   SENTINEL Backend E2E Test Suite
echo ═══════════════════════════════════════════════
echo.

:: Check FastAPI
echo Checking services...
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FastAPI not running on port 8000
    echo         Start with: cd backend ^&^& uvicorn app.main:app --reload
    exit /b 1
)
echo   FastAPI: running

:: Quick Redis check
"%PYTHON%" -c "import redis; redis.Redis().ping()" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Redis not running on port 6379
    echo         Start with: docker-compose up redis -d
    exit /b 1
)
echo   Redis:   running
echo   PostgreSQL: assumed running
echo.

:: Install test deps
echo [1/2] Installing test dependencies...
"%PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements_test.txt" -q
if errorlevel 1 (
    echo [ERROR] pip install failed
    exit /b 1
)

:: Run fast tests
echo [2/2] Running fast tests (excluding @pytest.mark.slow)...
echo.

"%PYTHON%" -m pytest "%BACKEND_DIR%\tests\e2e" -v -m "not slow" --tb=short --no-header -rN 2>&1

set "EXIT_CODE=!errorlevel!"
echo.
echo ═══════════════════════════════════════════════
echo To run ALL tests including slow ones:
echo   pytest tests\e2e\ -v --tb=short
echo.
echo To run a single file:
echo   pytest tests\e2e\test_04_scoring.py -v -s
echo.
echo To run the quick scenario script:
echo   python tests\e2e\run_single_scenario.py
echo ═══════════════════════════════════════════════

exit /b !EXIT_CODE!
