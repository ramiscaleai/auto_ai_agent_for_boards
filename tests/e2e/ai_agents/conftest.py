"""Shared fixtures and skip-gate for AI Agent e2e tests.

All e2e tests are skipped unless `E2E=1`. Individual tests may further gate
on specific env vars (e.g. OPENROUTER_API_KEY) or on a particular CLI being
installed + authenticated.
"""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _e2e_gate():
    if os.environ.get("E2E") != "1":
        pytest.skip("E2E tests gated by E2E=1", allow_module_level=False)


@pytest.fixture
def require_env(request):
    def _require(name: str):
        if not os.environ.get(name):
            pytest.skip(f"Env var {name} not set")
    return _require
