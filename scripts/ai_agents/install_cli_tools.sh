#!/usr/bin/env bash
set -euo pipefail

# Installs the three CLI tools the AI Agent layer depends on.
# Idempotent; safe to run repeatedly.

need_node() {
  if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node/npm not found. Install Node 20+ (nvm: https://github.com/nvm-sh/nvm) and re-run."
    exit 1
  fi
}

install_one() {
  local name="$1"; shift
  local pkg="$1"; shift
  if command -v "$name" >/dev/null 2>&1; then
    echo "  [$name] already installed: $(which $name)"
  else
    echo "  [$name] installing via npm global: $pkg"
    npm install -g "$pkg"
  fi
}

main() {
  need_node
  echo "Installing CLI tools for the AI Agent layer..."
  install_one codex "@openai/codex-cli"
  install_one gemini "@google/gemini-cli"
  install_one opencode "opencode-ai"
  echo ""
  echo "Next — authenticate each CLI interactively (one-time):"
  echo "  codex login      # opens browser for ChatGPT Plus/Pro auth"
  echo "  gemini           # first run prompts for Google OAuth"
  echo "  # opencode uses API keys from .env; no login step needed"
  echo ""
  echo "Then add API keys for the OpenCodeAgent paid backends to .env:"
  echo "  OPENROUTER_API_KEY=..."
  echo "  ANTHROPIC_API_KEY=..."
}

main "$@"
