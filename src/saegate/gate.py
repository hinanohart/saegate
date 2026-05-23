"""Gate — top-level entry point for saegate.

Composes:
    SAEProbe (or MockProbe) → Policy.evaluate → Decision (allow/deny/escalate)

Fail-closed semantics:
    Any probe load failure, runtime exception, timeout, or policy config error
    returns verdict=ESCALATE. We never silently fall back to ALLOW.

The Decision is *advisory*. The host (Claude Code / Cursor / OpenHands / etc.)
decides whether to act on it; saegate does not enforce policy itself.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import structlog

from saegate.policy import Policy
from saegate.probe import (
    MockProbe,
    ProbeConfig,
    ProbeError,
    ProbeLoadError,
    ProbeResult,
    ProbeRuntimeError,
    ProbeTimeoutError,
    SAEProbe,
    render_inspector_prompt,
)
from saegate.schemas import (
    Decision,
    Draft,
    FeatureActivation,
    Reason,
    ReasonCode,
    ToolCall,
    Verdict,
)
from saegate.telemetry import Telemetry

log = structlog.get_logger("saegate.gate")


ProbeLike = SAEProbe | MockProbe


@dataclass
class GateConfig:
    """Top-level gate configuration."""

    sandbox_required: bool = True
    use_mock_probe: bool = False
    probe_timeout_ms: int = 700


class Gate:
    """Composes probe + policy and returns an advisory Decision."""

    def __init__(
        self,
        policy: Policy,
        probe: ProbeLike | None = None,
        config: GateConfig | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.policy = policy
        self.config = config or GateConfig()
        if probe is not None:
            self.probe: ProbeLike = probe
        else:
            probe_cfg = ProbeConfig(timeout_ms=self.config.probe_timeout_ms)
            self.probe = MockProbe(probe_cfg) if self.config.use_mock_probe else SAEProbe(probe_cfg)
        self.telemetry = telemetry or Telemetry()

    def check(
        self,
        tool_call: ToolCall,
        draft: Draft | None = None,
        sandboxed: bool = False,
    ) -> Decision:
        """Probe the inspector LM and return an advisory Decision.

        Failure-mode contract:
            * ProbeLoadError       → escalate / PROBE_NOT_LOADED
            * ProbeRuntimeError    → escalate / PROBE_FAILED
            * ProbeTimeoutError    → escalate / PROBE_TIMEOUT
            * Policy config error  → escalate / CONFIG_ERROR
            * sandbox_required and not sandboxed → escalate / SANDBOX_REQUIRED
                                                   (does NOT skip the probe)
        """
        t0 = time.monotonic()
        draft = draft or Draft(text="")
        feature_ids = list(self.policy.required_feature_ids())
        prompt = render_inspector_prompt(
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            draft_text=draft.text,
        )

        try:
            if not self.probe.loaded:
                self.probe.load()
        except ProbeLoadError as exc:
            return self._fail_closed(
                ReasonCode.PROBE_NOT_LOADED, str(exc), prompt, t0, probe_loaded=False
            )
        except Exception as exc:
            return self._fail_closed(
                ReasonCode.PROBE_NOT_LOADED,
                f"unexpected load failure: {type(exc).__name__}",
                prompt,
                t0,
                probe_loaded=False,
            )

        if not feature_ids:
            return self._build_decision(
                verdict=Verdict.ESCALATE,
                reasons=[Reason(code=ReasonCode.POLICY_NO_FEATURES, detail="empty feature set")],
                activations=[],
                t0=t0,
                prompt=prompt,
            )

        try:
            result = self.probe.activations(prompt, feature_ids)
        except ProbeTimeoutError as exc:
            return self._fail_closed(
                ReasonCode.PROBE_TIMEOUT, str(exc), prompt, t0, probe_loaded=True
            )
        except (ProbeRuntimeError, ProbeError) as exc:
            return self._fail_closed(
                ReasonCode.PROBE_FAILED, str(exc), prompt, t0, probe_loaded=True
            )
        except Exception as exc:
            return self._fail_closed(
                ReasonCode.PROBE_FAILED,
                f"unexpected probe failure: {type(exc).__name__}",
                prompt,
                t0,
                probe_loaded=True,
            )

        try:
            verdict, reasons, fact_list = self.policy.evaluate(result, tool_call=tool_call)
        except Exception as exc:
            return self._fail_closed(
                ReasonCode.CONFIG_ERROR,
                f"policy.evaluate raised {type(exc).__name__}",
                prompt,
                t0,
                probe_loaded=True,
                activations=self._zero_activations(result, feature_ids),
            )

        if self.config.sandbox_required and not sandboxed:
            reasons = list(reasons) + [
                Reason(
                    code=ReasonCode.SANDBOX_REQUIRED,
                    detail="caller did not assert sandboxed=True",
                )
            ]
            if verdict == Verdict.ALLOW:
                verdict = Verdict.ESCALATE

        return self._build_decision(
            verdict=verdict,
            reasons=reasons,
            activations=fact_list,
            t0=t0,
            prompt=prompt,
            probe_loaded=True,
            mock=result.mock,
        )

    def explain(self, decision: Decision) -> str:
        """Human-readable explanation of a Decision (for MCP explain_decision)."""
        lines = [f"verdict: {decision.verdict.value}"]
        if decision.inspector_lm:
            lines.append(f"inspector_lm: {decision.inspector_lm}")
        if decision.sae_model_id:
            lines.append(f"sae_model_id: {decision.sae_model_id}")
        lines.append(f"elapsed_ms: {decision.elapsed_ms:.1f}")
        lines.append(f"probe_loaded: {decision.probe_loaded}")
        if decision.reasons:
            lines.append("reasons:")
            for r in decision.reasons:
                lines.append(f"  - {r.code.value}: {r.detail}")
        if decision.activations:
            lines.append("activations:")
            for a in decision.activations:
                marker = "*" if a.triggered else " "
                thr = f" (threshold={a.threshold:.3f})" if a.threshold is not None else ""
                label = f" [{a.label}]" if a.label else ""
                lines.append(f"  {marker} feature {a.feature_id}{label}: {a.value:.4f}{thr}")
        lines.append("(advisory only — host decides enforcement)")
        return "\n".join(lines)

    def _fail_closed(
        self,
        code: ReasonCode,
        detail: str,
        prompt: str,
        t0: float,
        *,
        probe_loaded: bool,
        activations: list[FeatureActivation] | None = None,
    ) -> Decision:
        log.warning("gate.fail_closed", code=code.value, detail=detail)
        return self._build_decision(
            verdict=Verdict.ESCALATE,
            reasons=[Reason(code=code, detail=detail)],
            activations=activations or [],
            t0=t0,
            prompt=prompt,
            probe_loaded=probe_loaded,
        )

    def _build_decision(
        self,
        *,
        verdict: Verdict,
        reasons: Iterable[Reason],
        activations: Iterable[FeatureActivation],
        t0: float,
        prompt: str,
        probe_loaded: bool = False,
        mock: bool = False,
    ) -> Decision:
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        cfg = getattr(self.probe, "config", None)
        inspector_lm = getattr(cfg, "inspector_lm", None) if cfg else None
        sae_model_id = getattr(cfg, "sae_model_id", None) if cfg else None
        if mock:
            sae_model_id = f"mock:{sae_model_id}" if sae_model_id else "mock"
        decision = Decision(
            verdict=verdict,
            reasons=list(reasons),
            activations=list(activations),
            elapsed_ms=elapsed_ms,
            probe_loaded=probe_loaded,
            inspector_lm=inspector_lm,
            sae_model_id=sae_model_id,
        )
        try:
            self.telemetry.record(decision=decision, prompt=prompt)
        except Exception:
            log.exception("telemetry.record_failed")
        return decision

    @staticmethod
    def _zero_activations(result: ProbeResult, feature_ids: list[int]) -> list[FeatureActivation]:
        out: list[FeatureActivation] = []
        for fid in feature_ids:
            out.append(
                FeatureActivation(
                    feature_id=fid,
                    value=float(result.activations.get(fid, 0.0)),
                )
            )
        return out


def _ensure_kwargs(_: Any) -> None:
    """Forward-compat placeholder."""
    return None
