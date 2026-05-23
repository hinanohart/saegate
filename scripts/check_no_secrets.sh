#!/usr/bin/env bash
# Grep-based secret pattern gate (recurrentlens / subjunctor pattern).
#
# Scans tracked files (and the staging area in pre-commit) for high-signal
# token shapes. False positives can be silenced with the
# `# saegate-no-secrets-ok` line marker.
#
# Intended as a fast first-line check; layer with gitleaks in CI for depth.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    FILES="$(git ls-files)"
else
    FILES="$(find . -type f -not -path './.git/*' -not -path './.venv/*' \
        -not -path './*.egg-info/*' -not -path './build/*' -not -path './dist/*')"
fi

# Excludes for the scanner script itself (which legitimately mentions patterns).
SELF="scripts/check_no_secrets.sh"

EXIT=0

scan_pattern() {
    local name="$1" pattern="$2"
    local matches
    matches="$(printf '%s\n' "$FILES" | xargs -I{} grep -InE "$pattern" "{}" 2>/dev/null \
        | grep -v 'saegate-no-secrets-ok' \
        | grep -vE "^${SELF}:" \
        | grep -vE '^configs/.*example' \
        | grep -vE '^README\.md:' \
        | grep -vE '^SECURITY\.md:' \
        || true)"
    if [ -n "$matches" ]; then
        echo "[secret-gate] $name matched in tracked files:"
        echo "$matches"
        EXIT=1
    fi
}

scan_pattern "github_pat"        'gh[oprsu]_[A-Za-z0-9]{30,}'
scan_pattern "openai_key"        'sk-[A-Za-z0-9_-]{20,}'
scan_pattern "anthropic_key"     'sk-ant-[A-Za-z0-9_-]{20,}'
scan_pattern "aws_key_id"        'AKIA[0-9A-Z]{16}'
scan_pattern "hf_token"          'hf_[A-Za-z0-9]{30,}'
scan_pattern "private_key_block" '-----BEGIN ([A-Z]+ )?PRIVATE KEY-----'
scan_pattern "bearer_header"     'Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._-]{20,}'

if [ "$EXIT" -ne 0 ]; then
    echo
    echo "[secret-gate] FAIL — possible secret(s) detected. If false positive,"
    echo "[secret-gate] add the comment marker 'saegate-no-secrets-ok' on the line,"
    echo "[secret-gate] or move the value to an env var / out-of-tree config."
    exit 1
fi

echo "[secret-gate] OK"
