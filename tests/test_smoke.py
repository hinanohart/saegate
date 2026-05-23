"""Smoke tests for saegate Phase 0.

Run with: pytest -xvs tests/test_smoke.py

Phase 0 tests are CPU-only and use MockProbe. Real-inference tests live behind
the `inference` and `gpu` markers and are deselected by default.
"""

from __future__ import annotations

import json

import pytest

from saegate import (
    Decision,
    Draft,
    FeatureActivation,
    Gate,
    Policy,
    SAEProbe,
    ToolCall,
    Verdict,
    __version__,
)
from saegate.gate import GateConfig
from saegate.policy import policy_from_dict
from saegate.probe import (
    MockProbe,
    ProbeConfig,
    ProbeLoadError,
    ProbeRuntimeError,
    render_inspector_prompt,
)
from saegate.schemas import ReasonCode
from saegate.telemetry import Telemetry, TelemetryConfig

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_public_api_surface_is_stable() -> None:
    """Every name the README promises must exist on the package."""
    import saegate

    assert __version__
    assert saegate.Gate is Gate
    assert saegate.Policy is Policy
    assert saegate.ToolCall is ToolCall
    assert saegate.Decision is Decision
    assert saegate.Verdict is Verdict
    assert saegate.SAEProbe is SAEProbe


# ---------------------------------------------------------------------------
# 1. Mock probe is deterministic
# ---------------------------------------------------------------------------


def test_mock_probe_is_deterministic() -> None:
    probe = MockProbe()
    a = probe.activations("hello world", [1, 7, 42])
    b = probe.activations("hello world", [1, 7, 42])
    assert a.activations == b.activations
    assert set(a.activations.keys()) == {1, 7, 42}
    for v in a.activations.values():
        assert 0.0 <= v <= 1.0
    assert a.mock is True


# ---------------------------------------------------------------------------
# 2. Allow path: no rule triggers when thresholds are unreachable
# ---------------------------------------------------------------------------


def _allow_policy() -> Policy:
    return policy_from_dict(
        {
            "version": 1,
            "mode": "advisory",
            "rules": [
                {"feature_id": 1, "label": "demo-a", "threshold": 2.0, "on_trigger": "escalate"},
                {"feature_id": 2, "label": "demo-b", "threshold": 2.0, "on_trigger": "escalate"},
            ],
        }
    )


def test_gate_allow_when_no_rule_triggers() -> None:
    gate = Gate(
        policy=_allow_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    decision = gate.check(
        ToolCall(name="read_file", arguments={"path": "README.md"}),
        Draft(text="reading project readme"),
    )
    assert decision.verdict == Verdict.ALLOW
    assert any(r.code == ReasonCode.POLICY_PASS for r in decision.reasons)
    assert len(decision.activations) == 2
    assert decision.is_advisory()


# ---------------------------------------------------------------------------
# 3. Escalate path: low threshold guarantees at least one trigger
# ---------------------------------------------------------------------------


def _escalate_policy() -> Policy:
    return policy_from_dict(
        {
            "version": 1,
            "mode": "advisory",
            "rules": [
                {"feature_id": 11, "label": "watch-a", "threshold": 0.0, "on_trigger": "escalate"},
                {"feature_id": 22, "label": "watch-b", "threshold": 0.0, "on_trigger": "escalate"},
            ],
        }
    )


def test_gate_escalates_when_thresholds_zero() -> None:
    gate = Gate(
        policy=_escalate_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    decision = gate.check(
        ToolCall(name="bash", arguments={"cmd": "ls"}),
        Draft(text="listing files"),
    )
    assert decision.verdict == Verdict.ESCALATE
    triggered = [a for a in decision.activations if a.triggered]
    assert len(triggered) == 2
    assert any(r.code == ReasonCode.SUSPECTED_FEATURE for r in decision.reasons)
    assert any(r.code == ReasonCode.POLICY_THRESHOLD for r in decision.reasons)


# ---------------------------------------------------------------------------
# 4. Fail-closed: probe runtime failure → escalate, never allow
# ---------------------------------------------------------------------------


class _BoomProbe:
    """Probe that loads fine but always raises on activations()."""

    def __init__(self) -> None:
        self.config = ProbeConfig()
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return True

    def load(self) -> None:
        return

    def activations(self, prompt: str, feature_ids: list[int]):  # type: ignore[override]
        raise ProbeRuntimeError("synthetic failure")


def test_gate_fail_closed_on_probe_runtime_error() -> None:
    gate = Gate(
        policy=_allow_policy(),
        probe=_BoomProbe(),  # type: ignore[arg-type]
        config=GateConfig(use_mock_probe=False, sandbox_required=False),
    )
    decision = gate.check(ToolCall(name="bash", arguments={"cmd": "rm -rf /"}))
    assert decision.verdict == Verdict.ESCALATE
    codes = {r.code for r in decision.reasons}
    assert ReasonCode.PROBE_FAILED in codes


class _UnloadableProbe:
    """Probe that raises on load()."""

    def __init__(self) -> None:
        self.config = ProbeConfig()
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return False

    def load(self) -> None:
        raise ProbeLoadError("synthetic load failure")

    def activations(self, prompt: str, feature_ids: list[int]):  # type: ignore[override]
        raise AssertionError("must not be called when load failed")


def test_gate_fail_closed_on_probe_load_error() -> None:
    gate = Gate(
        policy=_allow_policy(),
        probe=_UnloadableProbe(),  # type: ignore[arg-type]
        config=GateConfig(use_mock_probe=False, sandbox_required=False),
    )
    decision = gate.check(ToolCall(name="bash", arguments={}))
    assert decision.verdict == Verdict.ESCALATE
    codes = {r.code for r in decision.reasons}
    assert ReasonCode.PROBE_NOT_LOADED in codes


# ---------------------------------------------------------------------------
# 5. Sandbox-required: ALLOW → ESCALATE when sandboxed=False
# ---------------------------------------------------------------------------


def test_sandbox_required_demotes_allow_to_escalate() -> None:
    gate = Gate(
        policy=_allow_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=True),
    )
    decision_no_sandbox = gate.check(
        ToolCall(name="write_file", arguments={"path": "x"}),
        sandboxed=False,
    )
    decision_sandbox = gate.check(
        ToolCall(name="write_file", arguments={"path": "x"}),
        sandboxed=True,
    )
    assert decision_no_sandbox.verdict == Verdict.ESCALATE
    assert any(r.code == ReasonCode.SANDBOX_REQUIRED for r in decision_no_sandbox.reasons)
    assert decision_sandbox.verdict == Verdict.ALLOW


# ---------------------------------------------------------------------------
# 6. Schema round-trip: Decision is JSON-stable for MCP wire format
# ---------------------------------------------------------------------------


def test_decision_json_round_trip() -> None:
    gate = Gate(
        policy=_allow_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    decision = gate.check(ToolCall(name="read_file", arguments={"path": "X"}))
    raw = decision.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["verdict"] == decision.verdict.value
    restored = Decision.model_validate(parsed)
    assert restored.verdict == decision.verdict
    assert len(restored.activations) == len(decision.activations)


# ---------------------------------------------------------------------------
# 7. Render inspector prompt: deterministic + truncating
# ---------------------------------------------------------------------------


def test_render_inspector_prompt_truncates() -> None:
    big_args = {"data": "x" * 5000}
    prompt_a = render_inspector_prompt("bash", big_args, "draft")
    prompt_b = render_inspector_prompt("bash", big_args, "draft")
    assert prompt_a == prompt_b
    assert "TRUNCATED" in prompt_a
    assert "<saegate-probe>" in prompt_a
    assert '<tool_call name="bash">' in prompt_a


# ---------------------------------------------------------------------------
# 8. Policy validation catches malformed config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_raw",
    [
        {"version": 1, "rules": []},
        {"version": 2, "rules": [{"feature_id": 1}]},
        {"version": 1, "rules": [{"label": "no id"}]},
        {"version": 1, "rules": [{"feature_id": 1}, {"feature_id": 1}]},
        {"version": 1, "mode": "bogus", "rules": [{"feature_id": 1}]},
        {"version": 1, "rules": [{"feature_id": 1, "on_trigger": "allow"}]},
    ],
)
def test_policy_validation_rejects_bad_config(bad_raw: dict) -> None:
    with pytest.raises((ValueError, KeyError, TypeError)):
        policy_from_dict(bad_raw)


# ---------------------------------------------------------------------------
# 9. Telemetry: off-by-default, no file writes
# ---------------------------------------------------------------------------


def test_telemetry_disabled_writes_nothing(tmp_path) -> None:
    t = Telemetry(TelemetryConfig(enabled=False, dir=tmp_path))
    gate = Gate(
        policy=_allow_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
        telemetry=t,
    )
    gate.check(ToolCall(name="read_file", arguments={"path": "x"}))
    assert list(tmp_path.iterdir()) == []


def test_telemetry_enabled_writes_sha256_only(tmp_path) -> None:
    t = Telemetry(TelemetryConfig(enabled=True, dir=tmp_path, filename="trace.jsonl"))
    gate = Gate(
        policy=_allow_policy(),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
        telemetry=t,
    )
    gate.check(ToolCall(name="read_file", arguments={"path": "secret_path"}))
    path = tmp_path / "trace.jsonl"
    assert path.exists()
    record = json.loads(path.read_text().strip())
    assert "secret_path" not in path.read_text()
    assert "prompt_sha256" in record
    assert len(record["prompt_sha256"]) == 64
    assert record["verdict"] == "allow"


# ---------------------------------------------------------------------------
# 10. Empty rules-but-required-features path: escalate
# ---------------------------------------------------------------------------


def test_empty_feature_ids_escalates() -> None:
    class _NoOpPolicy(Policy):
        def required_feature_ids(self) -> list[int]:
            return []

    # _NoOpPolicy.evaluate would fail on empty rules, but the gate short-circuits.
    gate = Gate(
        policy=_NoOpPolicy(version=1, mode="advisory", rules=[]),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    decision = gate.check(ToolCall(name="bash", arguments={}))
    assert decision.verdict == Verdict.ESCALATE
    assert any(r.code == ReasonCode.POLICY_NO_FEATURES for r in decision.reasons)


# ---------------------------------------------------------------------------
# 11. FeatureActivation is exported and constructs cleanly
# ---------------------------------------------------------------------------


def test_feature_activation_construct() -> None:
    fa = FeatureActivation(feature_id=5, label="x", value=0.1, threshold=0.2, triggered=False)
    assert fa.feature_id == 5
    assert fa.triggered is False
