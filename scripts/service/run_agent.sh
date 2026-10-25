#!/usr/bin/env bash
# Called by the systemd service. Acquires a lock, runs one agent poll, then exits.
# Edge cases handled: stale PID, missing .env, missing venv, parallel invocations.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-$REPO_DIR/.run}"
LOCK_FILE="$RUNTIME_DIR/auto_ai_agent.lock"
PID_FILE="$RUNTIME_DIR/auto_ai_agent.pid"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/agent.log"
PYTHON="$REPO_DIR/.venv/bin/python"
ENV_FILE="$REPO_DIR/.env"

mkdir -p "$LOG_DIR"
install -d -m 700 "$RUNTIME_DIR"

# Systemd gives a minimal PATH (no nvm, no ~/.local/bin). Load the service
# user's environment so codex/gemini/opencode are found on PATH.
_HOME="$(eval echo ~"${SUDO_USER:-${USER:-$(id -un)}}")"
export HOME="$_HOME"
# shellcheck source=/dev/null
[[ -s "$_HOME/.nvm/nvm.sh" ]] && source "$_HOME/.nvm/nvm.sh"
export PATH="$_HOME/.local/bin:$PATH"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [run_agent] $*" | tee -a "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

# Prerequisite checks.

[[ -f "$ENV_FILE" ]]  || die ".env not found at $ENV_FILE - copy .env.example and fill it in"
[[ -x "$PYTHON" ]]    || die "Python venv not found at $PYTHON - create it and install project requirements first"

# Stale PID detection.

if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "Agent already running (PID $OLD_PID) - skipping this round"
        exit 0
    else
        log "Stale PID file (PID ${OLD_PID:-unknown} is dead) - clearing and continuing"
        rm -f "$PID_FILE" "$LOCK_FILE"
    fi
fi

# Exclusive lock prevents simultaneous systemd starts.

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "Lock already held - another instance is starting up - skipping"
    exit 0
fi

echo $$ > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT

# Run a single poll.

log "Starting agent run (PID $$)"
"$PYTHON" "$REPO_DIR/main.py" --run-once
log "Agent run finished (PID $$)"

# Best-effort: reclaim leaked opencode/Bun $TMPDIR extractions (see
# scripts/maintenance/clean_agent_tmp_leak.sh). Cleanup must never fail the poll.
"$REPO_DIR/scripts/maintenance/clean_agent_tmp_leak.sh" >>"$LOG_FILE" 2>&1 || true
