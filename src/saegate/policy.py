"""Policy — evaluate probe activations against a YAML feature catalog.

A Policy is a deterministic function:
    ProbeResult + ToolCall -> (Verdict, [Reason], [FeatureActivation])

The policy never raises on probe data; it only raises on its own config errors
(those are translated to ESCALATE by the Gate).

Design rules:
    * Feature IDs are *not* hardcoded — they live in YAML so users can swap
      catalogs without code changes (architecture Risk 2 mitigation).
    * Multiple features may trigger; the verdict is the maximum severity.
    * `mode: advisory` (default) never returns DENY — only ALLOW or ESCALATE.
      Users opt into DENY explicitly per feature.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from saegate.probe import ProbeResult
from saegate.schemas import (
    FeatureActivation,
    Reason,
    ReasonCode,
    ToolCall,
    Verdict,
)

DEFAULT_POLICY_VERSION = 1


@dataclass
class FeatureRule:
    feature_id: int
    label: str = ""
    threshold: float = 0.5
    on_trigger: Verdict = Verdict.ESCALATE
    note: str = ""

    def matches(self, activation_value: float) -> bool:
        return activation_value >= self.threshold


@dataclass
class Policy:
    """A loaded policy with rules and global config.

    Modes:
        advisory (default): triggered rules with `on_trigger: deny` are
            demoted to `escalate`. The gate therefore returns only
            `allow` or `escalate`.
        strict: rule verdicts are kept as written. A rule with
            `on_trigger: deny` returns `deny` when matched. Hosts that
            consume `deny` MUST still treat it as advisory.

    `allow` is never a valid `on_trigger` (caught at YAML load time).
    """

    version: int = DEFAULT_POLICY_VERSION
    mode: str = "advisory"  # "advisory" | "strict"
    rules: list[FeatureRule] = field(default_factory=list)
    description: str = ""

    def required_feature_ids(self) -> list[int]:
        return [r.feature_id for r in self.rules]

    def evaluate(
        self, result: ProbeResult, *, tool_call: ToolCall | None = None
    ) -> tuple[Verdict, list[Reason], list[FeatureActivation]]:
        """Returns (verdict, reasons, activation_records).

        Aggregation:
            * Each rule yields one FeatureActivation (always returned).
            * If rule.matches(value): contributes its on_trigger verdict.
            * Final verdict = max severity over triggered rules.
            * If no rule triggers: ALLOW with POLICY_PASS.
        """
        if not self.rules:
            raise ValueError("policy has zero rules")

        triggered_verdicts: list[Verdict] = []
        reasons: list[Reason] = []
        facts: list[FeatureActivation] = []

        for rule in self.rules:
            value = float(result.activations.get(rule.feature_id, 0.0))
            triggered = rule.matches(value)
            facts.append(
                FeatureActivation(
                    feature_id=rule.feature_id,
                    label=rule.label,
                    value=value,
                    threshold=rule.threshold,
                    triggered=triggered,
                )
            )
            if triggered:
                triggered_verdicts.append(rule.on_trigger)
                reasons.append(
                    Reason(
                        code=ReasonCode.SUSPECTED_FEATURE,
                        detail=(
                            f"feature {rule.feature_id} '{rule.label}' "
                            f"activation={value:.4f} >= threshold={rule.threshold:.3f}"
                        ),
                    )
                )

        if not triggered_verdicts:
            return (
                Verdict.ALLOW,
                [Reason(code=ReasonCode.POLICY_PASS, detail="no rule triggered")],
                facts,
            )

        if self.mode == "advisory":
            triggered_verdicts = [
                Verdict.ESCALATE if v == Verdict.DENY else v for v in triggered_verdicts
            ]

        verdict = _max_severity(triggered_verdicts)
        reasons.append(
            Reason(
                code=ReasonCode.POLICY_THRESHOLD,
                detail=f"{len(triggered_verdicts)} rule(s) triggered",
            )
        )
        return verdict, reasons, facts


_SEVERITY = {Verdict.ALLOW: 0, Verdict.ESCALATE: 1, Verdict.DENY: 2}


def _max_severity(verdicts: Iterable[Verdict]) -> Verdict:
    best = Verdict.ALLOW
    for v in verdicts:
        if _SEVERITY[v] > _SEVERITY[best]:
            best = v
    return best


def load_policy(path: str | Path) -> Policy:
    """Load a policy YAML from disk.

    Schema:
        version: 1
        mode: advisory | strict
        description: "..."
        rules:
          - feature_id: 12345
            label: "scheming-like"
            threshold: 0.6
            on_trigger: escalate | deny
            note: "..."
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"policy not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return policy_from_dict(raw)


def policy_from_dict(raw: Mapping[str, Any]) -> Policy:
    if not isinstance(raw, Mapping):
        raise ValueError("policy YAML must be a mapping")
    version = int(raw.get("version", DEFAULT_POLICY_VERSION))
    if version != 1:
        raise ValueError(f"unsupported policy version: {version}")
    mode = str(raw.get("mode", "advisory"))
    if mode not in ("advisory", "strict"):
        raise ValueError(f"policy.mode must be advisory|strict, got {mode!r}")
    description = str(raw.get("description", ""))
    rules_raw = raw.get("rules", [])
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("policy.rules must be a non-empty list")
    rules: list[FeatureRule] = []
    seen_ids: set[int] = set()
    for i, r in enumerate(rules_raw):
        if not isinstance(r, Mapping):
            raise ValueError(f"rule[{i}] must be a mapping")
        if "feature_id" not in r:
            raise ValueError(f"rule[{i}] missing feature_id")
        fid = int(r["feature_id"])
        if fid in seen_ids:
            raise ValueError(f"rule[{i}] duplicate feature_id {fid}")
        seen_ids.add(fid)
        threshold = float(r.get("threshold", 0.5))
        if threshold < 0 or threshold > 1_000_000:
            raise ValueError(f"rule[{i}] threshold out of range")
        on_trigger_raw = str(r.get("on_trigger", "escalate")).lower()
        try:
            on_trigger = Verdict(on_trigger_raw)
        except ValueError as exc:
            raise ValueError(
                f"rule[{i}] on_trigger must be one of "
                f"{[v.value for v in Verdict]}, got {on_trigger_raw!r}"
            ) from exc
        if on_trigger == Verdict.ALLOW:
            raise ValueError(f"rule[{i}] on_trigger=allow is meaningless")
        rules.append(
            FeatureRule(
                feature_id=fid,
                label=str(r.get("label", "")),
                threshold=threshold,
                on_trigger=on_trigger,
                note=str(r.get("note", "")),
            )
        )
    return Policy(
        version=version,
        mode=mode,
        rules=rules,
        description=description,
    )
