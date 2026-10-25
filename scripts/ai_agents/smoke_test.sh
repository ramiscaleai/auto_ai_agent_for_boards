#!/usr/bin/env bash
set -euo pipefail

# Runs the full validation suite for the AI Agent layer:
#   1. unit tests        — always runnable
#   2. e2e tests         — only if E2E=1 and CLIs are authenticated
#   3. CLI healthchecks  — always
# See spec section `Validation` for exit criteria.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== AI Agent layer smoke test =="

echo "[1/3] Unit tests"
.venv/bin/pytest tests/unit/ai_agents/ -q --cov=ai_agents --cov-report=term-missing

echo "[2/3] CLI healthchecks"
.venv/bin/python -c "
from ai_agents import CodexAgent, GeminiAgent, OpenCodeAgent
for a in (CodexAgent(), GeminiAgent(),
          OpenCodeAgent(name='openrouter', model='openrouter/openai/gpt-4o-mini', cost_tier='low')):
    print(f'  {a.name}: {\"up\" if a.healthcheck() else \"down\"}')
"

if [[ "${E2E:-0}" == "1" ]]; then
  echo "[3/3] E2E tests (E2E=1)"
  .venv/bin/pytest tests/e2e/ai_agents/ -v
else
  echo "[3/3] E2E tests skipped (set E2E=1 to run — costs may apply)"
fi

echo "== Done =="
