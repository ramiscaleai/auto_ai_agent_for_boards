"""E2E gate for orchestrator — requires E2E=1."""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _e2e_gate():
    if os.environ.get("E2E") != "1":
        pytest.skip("E2E tests gated by E2E=1")
