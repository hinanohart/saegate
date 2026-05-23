"""SAEProbe — lazy-load Llama-3.1-8B + SAE l19 and return per-feature activations.

Design constraints (from architecture):
  - Inspector LM is independent of the target coding agent's model (Llama ≠ Claude).
  - The probe is an *advisory behavioral surrogate*, not a faithful mirror.
  - Heavy imports (torch / transformer_lens / sae_lens) are deferred so that
    the rest of the package (schemas, policy, mcp_server stubs) runs CPU-only
    with zero ML deps.
  - On any load or runtime failure, raise a Probe* error; the Gate translates
    that into a fail-closed `escalate` decision.

License note:
  The default SAE artifact `Goodfire/Llama-3.1-8B-Instruct-SAE-l19` is built on
  Meta's Llama 3.1 model and inherits the LLAMA 3.1 COMMUNITY LICENSE. Users of
  saegate must accept that license at HF download time. saegate code itself is
  Apache-2.0; we do not redistribute weights.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_INSPECTOR_LM = "meta-llama/Llama-3.1-8B-Instruct"
DEFAULT_SAE_MODEL_ID = "Goodfire/Llama-3.1-8B-Instruct-SAE-l19"
DEFAULT_SAE_LAYER = 19
DEFAULT_MAX_TOKENS = 512
DEFAULT_LAST_K_AVG = 64


class ProbeError(RuntimeError):
    """Base class for all probe-side failures (load, runtime, timeout)."""


class ProbeLoadError(ProbeError):
    """Raised when the inspector LM or SAE artifact cannot be loaded."""


class ProbeRuntimeError(ProbeError):
    """Raised during forward / SAE encoding."""


class ProbeTimeoutError(ProbeError):
    """Raised when probe exceeds wall-clock budget."""


@dataclass
class ProbeConfig:
    inspector_lm: str = DEFAULT_INSPECTOR_LM
    sae_model_id: str = DEFAULT_SAE_MODEL_ID
    sae_layer: int = DEFAULT_SAE_LAYER
    max_tokens: int = DEFAULT_MAX_TOKENS
    last_k_avg: int = DEFAULT_LAST_K_AVG
    device: str = "auto"
    dtype: str = "bfloat16"
    timeout_ms: int = 700
    hf_token_env: str = "HF_TOKEN"

    def __post_init__(self) -> None:
        if self.max_tokens < 8 or self.max_tokens > 8192:
            raise ValueError("max_tokens out of range [8, 8192]")
        if self.last_k_avg < 1 or self.last_k_avg > self.max_tokens:
            raise ValueError("last_k_avg out of range")
        if self.timeout_ms < 50:
            raise ValueError("timeout_ms must be >= 50")


@dataclass
class ProbeResult:
    activations: dict[int, float] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    n_tokens: int = 0
    truncated: bool = False
    mock: bool = False


def _try_import_inference_stack() -> tuple[Any, Any, Any]:
    """Lazy import torch / transformer_lens / sae_lens.

    Returns (torch, HookedTransformer, SAE) or raises ProbeLoadError with a
    clean install hint.
    """
    try:
        torch = importlib.import_module("torch")
    except Exception as exc:
        raise ProbeLoadError(
            "torch not installed. Install with: pip install 'saegate[inference]'"
        ) from exc
    try:
        tl = importlib.import_module("transformer_lens")
    except Exception as exc:
        raise ProbeLoadError(
            "transformer_lens not installed. Install with: pip install 'saegate[inference]'"
        ) from exc
    try:
        sl = importlib.import_module("sae_lens")
    except Exception as exc:
        raise ProbeLoadError(
            "sae_lens not installed. Install with: pip install 'saegate[inference]'"
        ) from exc
    HookedTransformer = getattr(tl, "HookedTransformer", None)
    SAE = getattr(sl, "SAE", None)
    if HookedTransformer is None or SAE is None:
        raise ProbeLoadError("transformer_lens.HookedTransformer or sae_lens.SAE symbols not found")
    return torch, HookedTransformer, SAE


class SAEProbe:
    """Inspector LM + SAE forward.

    The probe holds resident model weights after first load. Re-create the
    instance to swap SAEs.
    """

    def __init__(self, config: ProbeConfig | None = None) -> None:
        self.config = config or ProbeConfig()
        self._model: Any | None = None
        self._sae: Any | None = None
        self._torch: Any | None = None
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Eagerly load inspector LM + SAE. Raises ProbeLoadError on failure."""
        if self._loaded:
            return
        torch, HookedTransformer, SAE = _try_import_inference_stack()
        self._torch = torch
        device = self._resolve_device(torch)
        try:
            self._model = HookedTransformer.from_pretrained(
                self.config.inspector_lm,
                device=device,
            )
        except Exception as exc:
            raise ProbeLoadError(
                f"failed to load inspector LM '{self.config.inspector_lm}'"
            ) from exc
        try:
            self._sae, _, _ = SAE.from_pretrained(
                release=self.config.sae_model_id,
                sae_id=f"blocks.{self.config.sae_layer}.hook_resid_post",
                device=device,
            )
        except Exception as exc:
            raise ProbeLoadError(
                f"failed to load SAE '{self.config.sae_model_id}' layer {self.config.sae_layer}"
            ) from exc
        self._loaded = True

    def activations(self, prompt: str, feature_ids: Sequence[int]) -> ProbeResult:
        """Run inspector LM + SAE; return mean activation over last-K tokens per feature.

        Raises:
            ProbeRuntimeError on tokenization / forward / SAE encode failure.
            ProbeTimeoutError if wall-clock exceeds config.timeout_ms.
        """
        if not self._loaded:
            raise ProbeRuntimeError("probe not loaded; call .load() first")
        if not feature_ids:
            return ProbeResult(activations={}, elapsed_ms=0.0, n_tokens=0)
        torch = self._torch
        assert torch is not None
        t0 = time.monotonic()
        try:
            tokens = self._model.to_tokens(prompt, prepend_bos=True)
            truncated = False
            if tokens.shape[-1] > self.config.max_tokens:
                tokens = tokens[..., : self.config.max_tokens]
                truncated = True
            n_tokens = int(tokens.shape[-1])
            hook_name = f"blocks.{self.config.sae_layer}.hook_resid_post"
            with torch.no_grad():
                _, cache = self._model.run_with_cache(tokens, names_filter=hook_name)
                resid = cache[hook_name]
                feats = self._sae.encode(resid)
            last_k = min(self.config.last_k_avg, n_tokens)
            window = feats[..., -last_k:, :]
            mean_per_feature = window.mean(dim=(0, 1))
            out: dict[int, float] = {}
            for fid in feature_ids:
                if fid < 0 or fid >= mean_per_feature.shape[-1]:
                    raise ProbeRuntimeError(
                        f"feature_id {fid} out of range [0,{mean_per_feature.shape[-1]})"
                    )
                out[int(fid)] = float(mean_per_feature[fid].item())
        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeRuntimeError(f"probe forward failed: {type(exc).__name__}") from exc
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if elapsed_ms > self.config.timeout_ms:
            raise ProbeTimeoutError(
                f"probe exceeded {self.config.timeout_ms}ms (took {elapsed_ms:.0f}ms)"
            )
        return ProbeResult(
            activations=out,
            elapsed_ms=elapsed_ms,
            n_tokens=n_tokens,
            truncated=truncated,
            mock=False,
        )

    def _resolve_device(self, torch: Any) -> str:
        if self.config.device != "auto":
            return self.config.device
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"


class MockProbe:
    """Deterministic, CPU-only probe for tests and CI.

    Returns activations as a hash-derived float in [0, 1] per (prompt, feature_id).
    NOT a real SAE. Production callers must use SAEProbe.
    """

    def __init__(self, config: ProbeConfig | None = None) -> None:
        self.config = config or ProbeConfig()
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return True

    def load(self) -> None:
        return

    def activations(self, prompt: str, feature_ids: Sequence[int]) -> ProbeResult:
        if not feature_ids:
            return ProbeResult(activations={}, elapsed_ms=0.1, n_tokens=0, mock=True)
        t0 = time.monotonic()
        out: dict[int, float] = {}
        for fid in feature_ids:
            if fid < 0:
                raise ProbeRuntimeError(f"feature_id {fid} must be >= 0")
            seed = hash((prompt, int(fid))) & 0xFFFFFFFF
            out[int(fid)] = (seed % 1000) / 1000.0
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        n_tokens = min(len(prompt.split()), self.config.max_tokens)
        return ProbeResult(
            activations=out,
            elapsed_ms=elapsed_ms,
            n_tokens=n_tokens,
            mock=True,
        )


def _escape_xml(text: str) -> str:
    """Escape `&`, `<`, `>`, and `"` to keep adversarial payloads from breaking
    the inspector prompt structure.

    Order matters: replace `&` first so we do not double-escape later entities.
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_inspector_prompt(
    tool_name: str,
    tool_args: dict[str, Any],
    draft_text: str,
    *,
    max_args_chars: int = 2000,
    max_draft_chars: int = 4000,
) -> str:
    """Render a structured prompt for the inspector LM.

    The prompt is plain text, deterministic, and capped in length. Truncation
    is preferred over raising, since the probe must not crash on long inputs.

    User-controlled values (tool_name, tool_args, draft_text) are XML-escaped
    so that a payload like ``</draft><tool_call name="evil">`` in the draft
    cannot inject an alternate tool_call frame into the inspector's view.
    """
    import json

    try:
        args_str = json.dumps(tool_args, ensure_ascii=False, sort_keys=True)
    except Exception:
        args_str = str(tool_args)
    if len(args_str) > max_args_chars:
        args_str = args_str[:max_args_chars] + "...[TRUNCATED]"
    draft = draft_text or ""
    if len(draft) > max_draft_chars:
        draft = draft[:max_draft_chars] + "...[TRUNCATED]"
    return (
        "<saegate-probe>\n"
        f"<draft>{_escape_xml(draft)}</draft>\n"
        f'<tool_call name="{_escape_xml(tool_name)}">{_escape_xml(args_str)}</tool_call>\n'
        "</saegate-probe>"
    )
