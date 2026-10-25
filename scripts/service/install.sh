#!/usr/bin/env bash
# Install or update the auto-ai-agent systemd timer and service.
# Re-running this script updates the unit files and restarts the timer.
# Requires sudo for writes to /etc/systemd/system.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_NAME="auto-ai-agent"
SYSTEMD_DIR="/etc/systemd/system"
ENV_FILE="$REPO_DIR/.env"
WRAPPER="$REPO_DIR/scripts/service/run_agent.sh"
SERVICE_USER="${SUDO_USER:-$USER}"

# Read poll interval from .env. Default: 5 minutes.

POLL_MIN=5
if [[ -f "$ENV_FILE" ]]; then
    val=$(grep -E '^(export[[:space:]]+)?AGENT_POLL_INTERVAL_MIN=' "$ENV_FILE" 2>/dev/null \
        | tail -n 1 \
        | cut -d= -f2- || true)
    val=$(printf '%s' "$val" | tr -d "\"'[:space:]")
    if [[ -n "$val" ]]; then
        if [[ "$val" =~ ^[1-9][0-9]*$ ]]; then
            POLL_MIN="$val"
        else
            echo "ERROR: AGENT_POLL_INTERVAL_MIN must be a positive integer, got '$val'"
            exit 1
        fi
    fi
fi

echo "Installing '$SERVICE_NAME' - poll interval: ${POLL_MIN} min after each run finishes"
echo "Repo: $REPO_DIR"

# Validate prerequisites.

[[ -f "$ENV_FILE" ]]    || { echo "ERROR: .env not found - copy .env.example and fill it in"; exit 1; }
[[ -x "$WRAPPER" ]]     || chmod +x "$WRAPPER"
[[ -d "$REPO_DIR/.venv" ]] || { echo "ERROR: .venv not found - create it and install project requirements first"; exit 1; }

# Write service unit.

sudo tee "$SYSTEMD_DIR/$SERVICE_NAME.service" > /dev/null << EOF
[Unit]
Description=Auto AI Agent for Boards - single poll run
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
ExecStart=$WRAPPER
StandardOutput=journal
StandardError=journal
# The timer controls scheduling.
EOF

# Write timer unit.

sudo tee "$SYSTEMD_DIR/$SERVICE_NAME.timer" > /dev/null << EOF
[Unit]
Description=Auto AI Agent for Boards - runs every ${POLL_MIN}min after last run finishes
Requires=$SERVICE_NAME.service

[Timer]
OnBootSec=1min
OnUnitInactiveSec=${POLL_MIN}min
Persistent=true
Unit=$SERVICE_NAME.service

[Install]
WantedBy=timers.target
EOF

# Enable and start.

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME.timer"

echo ""
echo "Installed and enabled '$SERVICE_NAME.timer'"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status $SERVICE_NAME.timer     # timer status + next trigger"
echo "  sudo systemctl status $SERVICE_NAME.service   # last run status"
echo "  journalctl -u $SERVICE_NAME.service -f        # live logs"
echo "  sudo systemctl start $SERVICE_NAME.service    # trigger a manual run now"
echo "  $REPO_DIR/scripts/service/uninstall.sh        # remove everything"
echo ""
sudo systemctl status "$SERVICE_NAME.timer" --no-pager || true
