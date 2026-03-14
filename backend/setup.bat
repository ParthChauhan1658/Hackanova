@echo off
echo ── SENTINEL backend setup ──────────────────────────────
echo.

echo [1/4] Creating virtual environment...
python -m venv venv
if errorlevel 1 (echo ERROR: python not found & exit /b 1)

echo [2/4] Activating venv...
call venv\Scripts\activate.bat

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip

echo [4/4] Installing dependencies...
pip install -r requirements.txt

echo.
echo ── Setup complete ───────────────────────────────────────
echo.
echo To start the server:
echo   venv\Scripts\activate
echo   uvicorn app.main:app --reload --port 8000
echo.
echo To run tests:
echo   venv\Scripts\activate
echo   pytest tests/ -v
