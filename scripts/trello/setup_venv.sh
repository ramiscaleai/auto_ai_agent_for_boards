#!/usr/bin/env bash
set -euo pipefail

# Creates .venv at repo root and installs Trello CLI dependencies.
# Replayable on any server running an older version of this repo.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO_ROOT/.venv"
REQ="$REPO_ROOT/scripts/trello/requirements.txt"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  echo "Created venv at $VENV"
fi

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REQ"
echo "Dependencies installed from $REQ"
