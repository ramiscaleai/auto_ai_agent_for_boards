#!/usr/bin/env bash
# Adds a user to the sudo group. Must be run as root: su -c "bash add_sudo.sh [username]"
set -euo pipefail

TARGET_USER="${1:-$SUDO_USER}"
TARGET_USER="${TARGET_USER:-$(logname 2>/dev/null || echo '')}"

if [[ -z "$TARGET_USER" ]]; then
    echo "Usage: su -c \"bash $0 <username>\""
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: must run as root — use: su -c \"bash $0 $TARGET_USER\""
    exit 1
fi

usermod -aG sudo "$TARGET_USER"
echo "Done. '$TARGET_USER' added to sudo group. Log out and back in for it to take effect."
