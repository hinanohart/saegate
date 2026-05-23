#!/usr/bin/env python3
"""Block commit if user-facing docs use overclaim phrases.

Runs in three layers (per architecture):
    1. pre-commit hook (this script invoked on staged docs)
    2. CI job (this script invoked on the full tree)
    3. Author self-check before writing user-facing copy

Usage:
    python scripts/honest_marketing_gate.py [path ...]
    # No args  → scan README.md, SECURITY.md, docs/**, configs/*.example.yaml

Exit codes:
    0   no violations
    1   one or more NG-word matches (printed with file:line:context)
    2   usage error

NG words come from the architecture memo. Suppress a false positive with the
`<!-- saegate-honest-ok -->` line marker.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

NG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("完全自動", re.compile(r"完全[にな]?[\s　]*自動")),
    ("永続的", re.compile(r"永続[的に]?")),
    ("完璧な", re.compile(r"完璧[なに]?")),
    ("絶対", re.compile(r"(?<![\w])絶対(?![\w])")),
    ("メンテゼロ", re.compile(r"メンテ[\s　]*ゼロ")),
    ("guaranteed", re.compile(r"\bguarantee(?:d|s)?\b", re.IGNORECASE)),
    ("100%_safe", re.compile(r"100\s*%\s*safe", re.IGNORECASE)),
    (
        "production-ready_without_advisory",
        re.compile(r"production[\s-]*ready", re.IGNORECASE),
    ),
    ("prevents_jailbreak", re.compile(r"prevent(?:s|ed|ing)?[\s-]+jailbreak", re.IGNORECASE)),
    ("detects_deception", re.compile(r"detect(?:s|ed|ing)?[\s-]+deception", re.IGNORECASE)),
    ("secures", re.compile(r"\bsecures\b", re.IGNORECASE)),
    ("stops_harmful", re.compile(r"stop(?:s|ped|ping)?[\s-]+harmful", re.IGNORECASE)),
]

FACT_CHECK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("saelens_broken", re.compile(r"SAELens[\s\-]*(is)?[\s]*broken", re.IGNORECASE)),
    ("anthropic_only", re.compile(r"Anthropic'?s[\s]+only", re.IGNORECASE)),
    ("state_of_the_art", re.compile(r"state[\s\-]+of[\s\-]+the[\s\-]+art", re.IGNORECASE)),
    ("first_of_its_kind", re.compile(r"\bfirst[\s\-]+of[\s\-]+its[\s\-]+kind", re.IGNORECASE)),
]

SUPPRESS_MARKER = "saegate-honest-ok"

DEFAULT_TARGETS = [
    "README.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs",
    "configs",
]


def iter_files(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
            continue
        for child in p.rglob("*"):
            if child.is_file() and child.suffix in {".md", ".yaml", ".yml", ".txt"}:
                out.append(child)
    return out


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return [(line_no, ng_label, context_snippet), ...] for violations in path.

    Special-cases:
        - "production-ready" is allowed only if the same line also contains
          the qualifier "advisory" (case-insensitive).
        - All matches honor the SUPPRESS_MARKER line marker.
        - "first" is checked only as "first of its kind" (whitelisted general use).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    violations: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SUPPRESS_MARKER in line:
            continue
        ll = line.lower()
        for label, pat in NG_PATTERNS:
            if not pat.search(line):
                continue
            if label == "production-ready_without_advisory" and "advisory" in ll:
                continue
            violations.append((lineno, label, line.strip()[:200]))
        for label, pat in FACT_CHECK_PATTERNS:
            if pat.search(line):
                violations.append((lineno, f"fact-check:{label}", line.strip()[:200]))
    return violations


def main(argv: list[str]) -> int:
    targets = argv[1:] if len(argv) > 1 else DEFAULT_TARGETS
    files = iter_files(targets)
    if not files:
        print("[honest-marketing] no target files; pass paths to scan.", file=sys.stderr)
        return 0
    total = 0
    for f in files:
        for lineno, label, ctx in scan_file(f):
            total += 1
            print(f"{f}:{lineno}: NG[{label}]: {ctx}")
    if total:
        print(
            f"\n[honest-marketing] FAIL — {total} violation(s). "
            "Add a 'saegate-honest-ok' line marker for justified usage.",
            file=sys.stderr,
        )
        return 1
    print(f"[honest-marketing] OK ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
