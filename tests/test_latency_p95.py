"""Latency smoke benchmark (MockProbe, CPU).

This is *not* a benchmark of the real SAEProbe — it verifies that the gate's
non-inference overhead (schema build, policy eval, telemetry hash, JSON dump)
stays well under the MCP timeout budget. Real-inference benchmarks live under
the `inference` marker and are not run in CI.
"""

from __future__ import annotations

import statistics
import time

import pytest

from saegate.gate import Gate, GateConfig
from saegate.policy import policy_from_dict
from saegate.probe import MockProbe
from saegate.schemas import ToolCall


def _policy_with_n_rules(n: int):
    return policy_from_dict(
        {
            "version": 1,
            "mode": "advisory",
            "rules": [
                {"feature_id": i, "label": f"f{i}", "threshold": 2.0, "on_trigger": "escalate"}
                for i in range(n)
            ],
        }
    )


@pytest.mark.parametrize("n_rules", [4, 16])
def test_gate_overhead_under_100ms(n_rules: int) -> None:
    gate = Gate(
        policy=_policy_with_n_rules(n_rules),
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    # Warm-up
    gate.check(ToolCall(name="warmup", arguments={}))
    samples: list[float] = []
    for _ in range(40):
        t0 = time.monotonic()
        gate.check(ToolCall(name="bench", arguments={"i": 1}))
        samples.append((time.monotonic() - t0) * 1000.0)
    samples.sort()
    p50 = samples[len(samples) // 2]
    p95 = samples[int(len(samples) * 0.95)]
    mean = statistics.mean(samples)
    # MockProbe is hash-only; this guards against accidental O(n) regressions.
    assert p95 < 100.0, f"p95={p95:.2f}ms exceeds 100ms (mean={mean:.2f}, p50={p50:.2f})"
