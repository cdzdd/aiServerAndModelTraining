# ruff: noqa: E402, F401
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from tests.conftest import database_url, migrated_engine  # noqa: F401
