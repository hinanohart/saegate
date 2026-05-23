"""saegate — Advisory MCP gate via Llama-3.1-8B SAE inspector.

This is a behavioral surrogate. Inspector LM activations on a rendered prompt
are not the target model's internal state. Use as advisory signal only.

Public surface:
    Decision, ToolCall, Draft, Reason, FeatureActivation  (schemas)
    Gate                                                  (gate.py)
    SAEProbe                                              (probe.py)
    Policy                                                (policy.py)
    FeatureCatalog                                        (features.py)
"""

from saegate.gate import Gate
from saegate.policy import Policy
from saegate.probe import ProbeError, ProbeLoadError, ProbeRuntimeError, SAEProbe
from saegate.schemas import (
    Decision,
    Draft,
    FeatureActivation,
    Reason,
    ReasonCode,
    ToolCall,
    Verdict,
)

__version__ = "0.0.1.post1"

__all__ = [
    "Decision",
    "Draft",
    "FeatureActivation",
    "Gate",
    "Policy",
    "ProbeError",
    "ProbeLoadError",
    "ProbeRuntimeError",
    "Reason",
    "ReasonCode",
    "SAEProbe",
    "ToolCall",
    "Verdict",
    "__version__",
]
