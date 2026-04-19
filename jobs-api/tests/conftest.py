"""Test fixtures for jobs-api.

The runtime image renames the directory `jobs-api/` (hyphen) to
`/app/jobs_api/` (underscore) so it's importable. To run pytest locally
without that rename, we load `server.py` directly via importlib and
expose it under the module name `jobs_api.server` so the production
import path stays the source of truth.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_JOBS_API_DIR = _HERE.parent
_REPO = _JOBS_API_DIR.parent

# Set BEFORE importing jobs_api so module-level os.environ.get(…) reads land here.
os.environ.setdefault("JOBS_API_INTERNAL_TOKEN", "test-token-deadbeef")
os.environ.setdefault("MAX_PARALLEL_JOBS", "2")
os.environ.setdefault("RUN_JOB_PY", str(_REPO / "scraper" / "run_job.py"))
os.environ.setdefault("OUT_DIR", "/tmp/jobs-api-test-output")


def _load_server():
    """Load server.py as `jobs_api.server` regardless of dir naming."""
    if "jobs_api" not in sys.modules:
        pkg = types.ModuleType("jobs_api")
        pkg.__path__ = [str(_JOBS_API_DIR)]
        sys.modules["jobs_api"] = pkg

    if "jobs_api.server" in sys.modules:
        return sys.modules["jobs_api.server"]

    spec = importlib.util.spec_from_file_location("jobs_api.server", _JOBS_API_DIR / "server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["jobs_api.server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module():
    return _load_server()


@pytest.fixture
def client(server_module):
    from fastapi.testclient import TestClient

    server_module._active.clear()
    return TestClient(server_module.app)


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"X-Internal-Auth": os.environ["JOBS_API_INTERNAL_TOKEN"]}
