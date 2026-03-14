@echo off
setlocal EnableDelayedExpansion

:: ── SENTINEL — Test Runner ────────────────────────────────────────────────────
:: Run from: D:\Hackanova\backend\
:: Usage:
::   run_tests.bat           — run all fast tests
::   run_tests.bat -v        — verbose output
::   run_tests.bat --slow    — include slow integration benchmarks

set "SCRIPT_DIR=%~dp0"

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
echo   SENTINEL Backend Test Suite
echo ============================================================
echo.

:: Install / sync dependencies
echo [1/3] Installing dependencies...
"%PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt" -q
if errorlevel 1 (
    echo [ERROR] pip install failed. Aborting.
    exit /b 1
)
echo [1/3] Dependencies OK.
echo.

:: Run tests
echo [2/3] Running tests...
echo.

if "%1"=="--slow" (
    "%PYTHON%" -m pytest tests/ -v --tb=short %2 %3
) else (
    "%PYTHON%" -m pytest tests/ -v --tb=short -m "not slow" %1 %2 %3
)

set "EXIT_CODE=!errorlevel!"
echo.

if !EXIT_CODE! EQU 0 (
    echo [3/3] All tests PASSED.
) else (
    echo [3/3] Some tests FAILED ^(exit code !EXIT_CODE!^).
)

echo.
exit /b !EXIT_CODE!
