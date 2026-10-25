#!/usr/bin/env bash
set -euo pipefail

# Installs the AI Agent layer Python deps into the repo's existing .venv.
# Replayable on any server running an older version.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO_ROOT/.venv"
REQ="$REPO_ROOT/scripts/ai_agents/requirements.txt"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  echo "Created venv at $VENV"
fi

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REQ"
echo "AI Agent layer dependencies installed from $REQ"
