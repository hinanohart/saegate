# Limitations

`saegate` ships with hard limits you should read before relying on it.

## 1. The inspector LM is a behavioral surrogate

The gate runs a *different model* (Llama-3.1-8B-Instruct) over a *rendered
prompt* — not the target agent's model on its own context. Activations seen
by the SAE therefore reflect how the inspector LM would have processed the
rendered string, not what the target agent was "thinking" when it produced
the tool-call.

Concretely:

- A feature labelled "deception-like" firing on the inspector says the
  inspector found something deception-like in the *rendered prompt*. It
  does not say the target agent intended deception.
- Cross-model transfer is unstudied for most SAE features at this scale.
  Treat any label as a working hypothesis.

## 2. Default catalog ships zero feature IDs

`configs/catalog.example.yaml` and `configs/policy.example.yaml` contain
placeholder IDs only. saegate makes no opinionated claim about which
Goodfire features mean what; you must run your own labelling pass before
the gate carries signal.

## 3. Thresholds are SAE-, layer-, and distribution-specific

Activation magnitudes depend on the SAE artifact, the layer, the
rendering format, and the distribution of tool-calls in your workload.
Thresholds copied from another deployment will not transfer cleanly.
Calibrate on a held-out scenario set.

## 4. Fail-closed means *escalate*, not *deny*

A probe load failure, runtime exception, timeout, or policy config error
returns `escalate` so a human can adjudicate. saegate never silently
falls back to `allow`. It also does not auto-`deny`: deny is only emitted
when an explicit rule with `on_trigger: deny` matches *and* `mode: strict`
is set in the policy.

## 5. Latency budget

- Default `timeout_ms = 700`.
- Real SAE inference on a 16 GB GPU is the dominant cost; CPU is not a
  supported production path. The mock probe is fast (<100 ms) but
  obviously carries no signal.
- A `gate_check` that exceeds the budget returns `escalate` with
  `PROBE_TIMEOUT`.

## 6. Steering is not supported

saegate is observation-only by design. It reads SAE activations; it does
not patch, scale, or ablate features. Steering-based defenses have a known
attack surface (e.g. *Rogue Scalpel*, arXiv:2509.22067) and are out of
scope.

## 7. License inheritance for the SAE artifact

The default SAE is built on Llama 3.1 and inherits the LLAMA 3.1
COMMUNITY LICENSE. saegate does not redistribute weights; the license
attaches at HF download time. See [NOTICE.md](../NOTICE.md).

## 8. Not a substitute for a sandbox

Sandboxing untrusted tool-calls is the load-bearing security control.
saegate is a flag, not a wall. The `sandbox_required=True` default exists
to make this explicit: callers must assert `sandboxed=True` or the gate
escalates on every `allow`.
