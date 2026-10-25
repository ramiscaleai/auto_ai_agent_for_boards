#!/usr/bin/env bash
# Stop, disable, and remove the auto-ai-agent systemd timer and service.
# Does not delete code, logs, or .env; only the systemd units are removed.
set -euo pipefail

SERVICE_NAME="auto-ai-agent"
SYSTEMD_DIR="/etc/systemd/system"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-$REPO_DIR/.run}"
PID_FILE="$RUNTIME_DIR/auto_ai_agent.pid"
LOCK_FILE="$RUNTIME_DIR/auto_ai_agent.lock"

echo "Stopping and disabling '$SERVICE_NAME'..."

# Stop any running agent gracefully.

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        echo "Sending SIGTERM to running agent (PID $PID)..."
        kill -TERM "$PID" 2>/dev/null || true
        for i in $(seq 1 30); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "Agent did not stop in 30s; sending SIGKILL"
            kill -KILL "$PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_FILE" "$LOCK_FILE"
fi

# Stop and disable timer and service.

sudo systemctl stop  "$SERVICE_NAME.timer"   2>/dev/null || true
sudo systemctl stop  "$SERVICE_NAME.service" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME.timer" 2>/dev/null || true

# Remove unit files.

sudo rm -f "$SYSTEMD_DIR/$SERVICE_NAME.service" "$SYSTEMD_DIR/$SERVICE_NAME.timer"
sudo systemctl daemon-reload

echo ""
echo "'$SERVICE_NAME' timer and service stopped, disabled, and removed."
echo "  Logs are still at: $(dirname "${BASH_SOURCE[0]}")/../../logs/agent.log"
echo "  Re-enable with:    $(dirname "${BASH_SOURCE[0]}")/install.sh"
