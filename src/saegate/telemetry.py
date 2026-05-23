"""Privacy-first local telemetry.

Records gate decisions to a local JSONL file (default off) with no raw prompts:
    - sha256(prompt) only
    - verdict, reason codes, elapsed_ms, n_activations

No network calls. No PII. The file lives under ~/.saegate/telemetry.jsonl by
default and can be disabled via env SAEGATE_TELEMETRY=off.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saegate.schemas import Decision, Reason

DEFAULT_DIR = Path.home() / ".saegate"
DEFAULT_FILE = "telemetry.jsonl"


@dataclass
class TelemetryConfig:
    enabled: bool = False
    dir: Path = DEFAULT_DIR
    filename: str = DEFAULT_FILE


class Telemetry:
    """Local-only structured trace writer."""

    def __init__(self, config: TelemetryConfig | None = None) -> None:
        self.config = config or TelemetryConfig()
        if os.environ.get("SAEGATE_TELEMETRY", "off").lower() == "on":
            self.config.enabled = True

    def record(self, *, decision: Decision, prompt: str) -> None:
        if not self.config.enabled:
            return
        self.config.dir.mkdir(parents=True, exist_ok=True)
        path = self.config.dir / self.config.filename
        payload = {
            "ts": time.time(),
            "verdict": decision.verdict.value,
            "elapsed_ms": round(decision.elapsed_ms, 2),
            "n_activations": len(decision.activations),
            "n_triggered": sum(1 for a in decision.activations if a.triggered),
            "probe_loaded": decision.probe_loaded,
            "inspector_lm": decision.inspector_lm,
            "sae_model_id": decision.sae_model_id,
            "reason_codes": [r.code.value for r in decision.reasons],
            "prompt_sha256": _sha256(prompt),
            "prompt_len": len(prompt),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def summarize_reasons(reasons: Sequence[Reason]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in reasons:
        out[r.code.value] = out.get(r.code.value, 0) + 1
    return out


def make_safe_record(decision: Decision, prompt: str) -> dict[str, Any]:
    return {
        "verdict": decision.verdict.value,
        "elapsed_ms": round(decision.elapsed_ms, 2),
        "n_activations": len(decision.activations),
        "reason_codes": [r.code.value for r in decision.reasons],
        "prompt_sha256": _sha256(prompt),
        "prompt_len": len(prompt),
    }
