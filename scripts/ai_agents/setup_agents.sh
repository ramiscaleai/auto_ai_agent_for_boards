#!/usr/bin/env bash
# Validates, installs, and reports status for every agent in the fallback chain.
# Safe to run repeatedly. Run as your normal user (not root).
set -euo pipefail

# Source nvm so node/npm binaries are on PATH (needed in clean envs).
_HOME="${HOME:-$(eval echo ~"${USER:-$(whoami)}")}"
# shellcheck source=/dev/null
[[ -s "$_HOME/.nvm/nvm.sh" ]] && source "$_HOME/.nvm/nvm.sh"
export PATH="$_HOME/.local/bin:$PATH"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$REPO_DIR/.env"

# Colour helpers (disabled when stdout is not a tty).
if [[ -t 1 ]]; then
    R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' B='\033[0;34m' N='\033[0m'
else
    R='' G='' Y='' B='' N=''
fi
ok()   { echo -e "  ${G}[✓]${N} $*"; }
warn() { echo -e "  ${Y}[!]${N} $*"; }
fail() { echo -e "  ${R}[✗]${N} $*"; }
info() { echo -e "  ${B}   ${N} $*"; }

# Read a value from .env without exposing secrets (returns empty string if unset).
env_key_len() {
    local key="$1"
    local val
    val=$(grep -E "^(export[[:space:]]+)?${key}=" "$ENV_FILE" 2>/dev/null \
        | tail -n1 | cut -d= -f2- | tr -d "\"' " || true)
    echo "${#val}"
}

# ── Node prerequisite ────────────────────────────────────────────────────────

check_node() {
    if ! command -v node >/dev/null 2>&1; then
        fail "node/npm not found — install Node 20+ first"
        info "Recommended: https://github.com/nvm-sh/nvm"
        exit 1
    fi
    ok "node $(node --version)  npm $(npm --version)"
}

# ── Binary: install if missing, report location ──────────────────────────────

ensure_binary() {
    local name="$1" pkg="$2"
    if command -v "$name" >/dev/null 2>&1; then
        info "binary: $(command -v "$name")"
        return 0
    fi
    warn "$name not found — installing $pkg ..."
    if npm install -g "$pkg" >/dev/null 2>&1; then
        ok "$name installed at $(command -v "$name" 2>/dev/null || echo '?')"
    else
        fail "npm install -g $pkg failed — install manually and re-run"
        return 1
    fi
}

# ── Codex (OpenAI, ChatGPT Plus/Pro subscription) ───────────────────────────

check_codex() {
    echo ""
    echo -e "${B}── codex  (OpenAI — ChatGPT Plus/Pro subscription)${N}"
    ensure_binary "codex" "@openai/codex-cli" || return
    if [[ -f "$_HOME/.codex/auth.json" ]]; then
        ok "authenticated  (~/.codex/auth.json present)"
    else
        warn "NOT authenticated"
        info "Run interactively (not as root):  codex login"
    fi
}

# ── Gemini (Google, free tier via OAuth) ─────────────────────────────────────

check_gemini() {
    echo ""
    echo -e "${B}── gemini  (Google — free tier via OAuth)${N}"
    ensure_binary "gemini" "@google/gemini-cli" || return
    local found=0
    for dir in "$_HOME/.gemini" "$_HOME/.config/gemini" "$_HOME/.config/google-gemini-cli"; do
        if [[ -d "$dir" ]] && compgen -G "$dir/*.json" >/dev/null 2>&1; then
            ok "authenticated  ($dir)"
            found=1; break
        fi
    done
    if [[ $found -eq 0 ]]; then
        warn "NOT authenticated"
        info "Run interactively (not as root):  gemini   (opens Google OAuth on first run)"
    fi
}

# ── OpenCode (API-key based: OpenRouter + Anthropic) ─────────────────────────

check_opencode() {
    echo ""
    echo -e "${B}── opencode  (API-key based: openrouter + claude slots)${N}"
    ensure_binary "opencode" "opencode-ai" || return
    if [[ ! -f "$ENV_FILE" ]]; then
        warn ".env not found — cannot check API keys"
        return
    fi
    local or_len claude_len
    or_len=$(env_key_len "OPENROUTER_API_KEY")
    claude_len=$(env_key_len "ANTHROPIC_API_KEY")
    if [[ $or_len -gt 0 ]]; then
        ok "OPENROUTER_API_KEY set  (${or_len} chars)"
    else
        fail "OPENROUTER_API_KEY missing in .env  →  openrouter slot disabled"
    fi
    if [[ $claude_len -gt 0 ]]; then
        ok "ANTHROPIC_API_KEY set  (${claude_len} chars)"
    else
        fail "ANTHROPIC_API_KEY missing in .env  →  claude slot disabled"
    fi
    if [[ $or_len -eq 0 && $claude_len -eq 0 ]]; then
        warn "opencode installed but no API keys — add at least one to .env"
    fi
}

# ── Summary ───────────────────────────────────────────────────────────────────

print_summary() {
    echo ""
    echo "────────────────────────────────────────────────────────────────"
    echo "Fallback chain: codex → gemini → openrouter → claude"
    echo "At least one agent must be fully ready for the system to work."
    echo ""
    echo "Auth commands (run as your normal user, not root):"
    info "codex login   — ChatGPT Plus/Pro browser auth"
    info "gemini        — Google OAuth (first run opens browser)"
    info "Add OPENROUTER_API_KEY / ANTHROPIC_API_KEY to .env for paid slots"
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
    echo "AI Agent Setup & Validation"
    echo "════════════════════════════════════════════════════════════════"
    [[ -f "$ENV_FILE" ]] || warn ".env not found at $ENV_FILE — some checks skipped"
    check_node
    check_codex
    check_gemini
    check_opencode
    print_summary
}

main "$@"
