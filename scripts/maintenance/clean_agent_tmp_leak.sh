#!/usr/bin/env bash
# clean_agent_tmp_leak.sh — reclaim leaked opencode/Bun $TMPDIR extractions.
#
# opencode is a Bun standalone binary: on EVERY launch it extracts its embedded
# native libs (miniaudio, ~5.3 MB each) into $TMPDIR and never deletes them. Any
# process that runs opencode with TMPDIR pointed at the shared agent temp
# (/tmp/claude-<uid>) therefore leaks one ~5.3 MB ``.<hash>-NNNN.so`` per call
# (~1.5 GiB/day observed). This janitor only reclaims those orphans; the real
# fix is opencode itself / a private per-call TMPDIR (see README
# "opencode $TMPDIR leak").
#
# Safety model — delete only what is BOTH an unambiguous leak AND old enough that
# no live session can still need it:
#   * Pattern: only Bun leak signatures directly under the temp root — hidden
#     ``.<hash>.so`` / ``.<hash>.tmp`` files plus our own ``opencode-tmp-*`` dirs.
#     Session/work dirs (``-home-<user>-git-*``, ``<uuid>``, ``*_e2e_*`` …) never match.
#   * Age: a 24h grace window (LEAK_MIN_AGE_MIN, default 1440). A file is removed
#     only once it is older than the window, so any extraction belonging to an
#     opencode session started within the last day is preserved even if that
#     session is still running. (Deleting an in-use one is in fact still safe —
#     unlinking an mmap'd file on Linux leaves the running process's handle
#     intact — the window is an extra belt-and-suspenders margin for long runs.)
# Idempotent and best-effort; intended to run on a schedule.
#
# Env overrides:
#   AGENT_TMP_ROOT   temp dir to clean        (default: /tmp/claude-$(id -u))
#   LEAK_MIN_AGE_MIN don't touch newer items  (default: 1440 = 24h)
#   DRY_RUN=1        report only, delete nothing
set -uo pipefail

TMP_ROOT="${AGENT_TMP_ROOT:-/tmp/claude-$(id -u)}"
MIN_AGE_MIN="${LEAK_MIN_AGE_MIN:-1440}"
DRY_RUN="${DRY_RUN:-0}"
TAG="[tmp-janitor]"
AGE_H=$(( MIN_AGE_MIN / 60 ))

[ -d "$TMP_ROOT" ] || { echo "$TAG $TMP_ROOT absent; nothing to do"; exit 0; }

_find_targets() {
  find "$TMP_ROOT" -maxdepth 1 -mmin "+$MIN_AGE_MIN" \( \
      -type f \( -name '.*.so' -o -name '.*.tmp' \) \
      -o -type d -name 'opencode-tmp-*' \
    \) 2>/dev/null
}

n=$(_find_targets | wc -l)
if [ "$n" -eq 0 ]; then
  echo "$TAG nothing to clean (age > ${MIN_AGE_MIN}m / ~${AGE_H}h) in $TMP_ROOT"
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "$TAG DRY_RUN: would remove $n orphaned opencode extraction(s) older than ~${AGE_H}h from $TMP_ROOT"
  exit 0
fi

find "$TMP_ROOT" -maxdepth 1 -mmin "+$MIN_AGE_MIN" -type f \( -name '.*.so' -o -name '.*.tmp' \) -delete 2>/dev/null
find "$TMP_ROOT" -maxdepth 1 -mmin "+$MIN_AGE_MIN" -type d -name 'opencode-tmp-*' -exec rm -rf {} + 2>/dev/null
echo "$TAG removed $n orphaned opencode extraction(s) older than ~${AGE_H}h from $TMP_ROOT"
