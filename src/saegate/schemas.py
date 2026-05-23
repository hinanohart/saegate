"""Pydantic schemas for saegate.

Stable contract for MCP tool inputs/outputs. Backwards-incompatible changes
require a major version bump.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class ReasonCode(StrEnum):
    POLICY_PASS = "policy_pass"
    POLICY_THRESHOLD = "policy_threshold"
    POLICY_NO_FEATURES = "policy_no_features"
    PROBE_FAILED = "probe_failed"
    PROBE_TIMEOUT = "probe_timeout"
    PROBE_NOT_LOADED = "probe_not_loaded"
    CONFIG_ERROR = "config_error"
    SANDBOX_REQUIRED = "sandbox_required"
    SUSPECTED_FEATURE = "suspected_feature"
    UNKNOWN_TOOL = "unknown_tool"


class ToolCall(BaseModel):
    """A tool-call the coding agent is about to execute."""

    name: str = Field(..., min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)
    server: str | None = Field(default=None, max_length=256)

    @field_validator("name")
    @classmethod
    def _name_no_control_chars(cls, v: str) -> str:
        # Reject all C0 controls (0x00–0x1F) and DEL (0x7F). The inspector
        # prompt embeds `name` inside an XML-style attribute; control chars
        # would either corrupt that frame (NUL splicing the token), or sneak
        # through logging / JSONL telemetry as binary noise.
        for ch in v:
            if ord(ch) < 0x20 or ord(ch) == 0x7F:
                raise ValueError(
                    f"tool name must not contain control characters (got 0x{ord(ch):02X})"
                )
        return v


class Draft(BaseModel):
    """The agent's draft message preceding the tool call."""

    text: str = Field(default="", max_length=32_000)
    role: Literal["assistant"] = "assistant"


class FeatureActivation(BaseModel):
    """Per-feature activation summary returned by the SAE probe."""

    feature_id: int = Field(..., ge=0)
    label: str = Field(default="", max_length=512)
    value: float
    threshold: float | None = None
    triggered: bool = False


class Reason(BaseModel):
    code: ReasonCode
    detail: str = Field(default="", max_length=1024)


class Decision(BaseModel):
    """The Gate's verdict + reasoning trace."""

    verdict: Verdict
    reasons: list[Reason] = Field(default_factory=list)
    activations: list[FeatureActivation] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    probe_loaded: bool = False
    inspector_lm: str | None = None
    sae_model_id: str | None = None

    def is_advisory(self) -> bool:
        """All saegate decisions are advisory; the host is the policy decider."""
        return True
