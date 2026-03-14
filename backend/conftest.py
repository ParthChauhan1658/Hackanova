"""
Root conftest for SENTINEL backend tests.
- Loads .env (if python-dotenv is installed) so DATABASE_URL / API keys are set.
- Adds the backend root to sys.path so `app.*` imports always resolve.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend root is on sys.path
_BACKEND_ROOT = Path(__file__).parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Load .env before any test module is imported (override=False keeps existing env vars)
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — env vars must be set by the shell
