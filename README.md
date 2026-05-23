# saegate

> An advisory MCP gate that probes coding-agent tool-calls via a Llama-3.1-8B SAE inspector — observation only, fail-closed escalate, sandbox required.

[![CI](https://github.com/hinanohart/saegate/actions/workflows/ci.yml/badge.svg)](https://github.com/hinanohart/saegate/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## What this is

`saegate` is an MCP server that exposes a **`gate_check`** tool. Hosts (Claude
Code, Cursor, OpenHands, opencode, aider, …) call `gate_check` *before*
executing a tool-call. The gate:

1. Renders a structured prompt from the tool-call + the agent's draft.
2. Runs that prompt through an **inspector LM** (`Llama-3.1-8B-Instruct`).
3. Reads the residual stream at layer 19 via a **sparse autoencoder**
   (`Goodfire/Llama-3.1-8B-Instruct-SAE-l19`).
4. Compares per-feature activations against a user-supplied YAML policy.
5. Returns `allow | escalate` — or `deny`, only if your policy opts in
   explicitly (`mode: strict` plus a rule with `on_trigger: deny`). In the
   default `mode: advisory`, deny is auto-demoted to escalate.

The host decides whether to honor the verdict. saegate never blocks anything
on its own.

## What this is NOT

- **Not a security boundary.** saegate is an advisory signal layered on top
  of a sandbox. Run untrusted coding agents in a sandbox regardless.
- **Not a faithful read of the target agent's state.** The inspector LM is a
  *behavioral surrogate*: activations on a rendered prompt are not the
  target model's internal state. Treat the output as an external check, not
  introspection.
- **Not calibrated.** The default catalog ships zero feature IDs. You must
  do your own labelling pass on the SAE before the gate carries signal.
- **Not a substitute for human review** of high-impact actions. Escalations
  are meant to be surfaced to a human; saegate has no ability to evaluate
  them itself.

## Why an inspector LM (not the target's own activations)?

- **Vendor-agnostic.** Works the same way whether the host is Claude Code,
  Cursor, OpenHands, or anything else that speaks MCP. The gate does not
  depend on the target model's weights being open or instrumentable.
- **No model-internal access required.** saegate runs entirely outside the
  agent loop. It does not need to attach hooks to the agent's own forward
  pass or rely on logprob exposure.
- **Honest trade-off.** Because the inspector LM is a separate model, the
  gate is a behavioral surrogate, not a mirror. See
  [docs/limitations.md](docs/limitations.md).

## Status

`v0.0.1` Phase 0 scaffold (2026-05-23):

- Schemas, gate, policy, mock probe, MCP stdio server, CLI — all working CPU-only.
- 28 pytest tests covering allow / escalate / fail-closed (load /
  runtime / timeout) / sandbox / JSON round-trip / policy validation /
  telemetry / latency overhead / MCP roundtrip / prompt-injection escape.
- Honest-marketing gate + secret-pattern gate + ruff/format CI.
- **Real SAE inference and a calibrated feature catalog are not in v0.0.1.**
  They land in v0.1.0 once GPU-side validation is done.
- **Latency targets are unverified on real inference.** The architecture pins
  a p95 budget of 500 ms with a 700 ms hard timeout; v0.0.1 only verifies
  gate overhead with the mock probe (< 100 ms). Real-GPU benchmarks land in
  v0.1.0.

See [CHANGELOG.md](CHANGELOG.md) for the roadmap to v0.1.0+.

## Installation

```bash
# Minimal (mock probe only; CPU; runs on Python 3.11 / 3.12)
pip install -e .

# With MCP stdio support
pip install -e '.[mcp]'

# With real SAE inference (GPU recommended; ~16 GB VRAM for Llama-3.1-8B + SAE)
pip install -e '.[inference]'

# Developer install
pip install -e '.[dev]'

# Enable local pre-commit hooks (recommended for contributors)
pip install pre-commit && pre-commit install
```

## Quickstart (mock mode, CPU)

```bash
# Run a single probe against the example policy.
saegate probe-once \
  configs/policy.example.yaml \
  --tool bash \
  --args '{"cmd": "ls -la"}' \
  --draft "listing files for context" \
  --sandboxed \
  --mock

# Start the MCP server (mock probe; for wiring tests).
saegate serve configs/policy.example.yaml --catalog configs/catalog.example.yaml --mock
```

The shipped example policy and catalog use **placeholder feature IDs** with
threshold `0.8`. With the deterministic `MockProbe` they usually return
`escalate` (sandbox-required default) — the value is the wiring path, not
the verdict content. Calibrate against real activations before drawing any
conclusions from a verdict.

## Wiring into a host

### Claude Code

Add to your Claude Code MCP config (`~/.claude/mcp.json` or per-project
`.mcp.json`):

```json
{
  "mcpServers": {
    "saegate": {
      "command": "saegate",
      "args": [
        "serve",
        "/abs/path/to/policy.yaml",
        "--catalog", "/abs/path/to/catalog.yaml",
        "--mock"
      ]
    }
  }
}
```

Then call `gate_check` from the host before executing a tool-call.

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "saegate": {
      "command": "saegate",
      "args": ["serve", "/abs/path/to/policy.yaml", "--mock"]
    }
  }
}
```

### OpenHands / opencode / aider

Any MCP-speaking host can launch `saegate serve <policy>` as a stdio child
process. The wire-format is fixed by `saegate.schemas.Decision`.

### Host-side pseudocode

```python
async def before_tool_call(tool_name, args, draft):
    result = await mcp.call("saegate", "gate_check", {
        "tool_name": tool_name,
        "arguments": args,
        "draft_text": draft,
        "sandboxed": True,
    })
    if result["verdict"] in ("escalate", "deny"):
        await ask_human(result)  # advisory: host still chooses
```

A wire-format test in `tests/test_smoke.py::test_decision_json_round_trip`
pins the Decision JSON shape.

## Policy schema

```yaml
version: 1
mode: advisory          # advisory: never returns deny (only allow/escalate)
description: "your notes"
rules:
  - feature_id: 12345   # required
    label: "..."        # advisory only
    threshold: 0.6      # required
    on_trigger: escalate # escalate | deny
    note: "..."         # free text
```

See `configs/policy.example.yaml`.

## License

- This repository: Apache 2.0 (see [LICENSE](LICENSE)).
- The default SAE artifact `Goodfire/Llama-3.1-8B-Instruct-SAE-l19` is built
  on Meta's Llama 3.1 and inherits the **LLAMA 3.1 COMMUNITY LICENSE**. By
  using the default `inference` extras you accept that license at download
  time. saegate does **not** redistribute weights. See [NOTICE.md](NOTICE.md).

## Citation

If you build on saegate, please cite the repo:

```bibtex
@software{saegate2026,
  author  = {hinanohart},
  title   = {saegate: advisory MCP gate via SAE inspector},
  year    = {2026},
  url     = {https://github.com/hinanohart/saegate}
}
```

## Related work

- [SAELens](https://github.com/jbloomAus/SAELens) — SAE training + loading
- [TransformerLens](https://github.com/TransformerLensOrg/TransformerLens) — model hooks
- [circuit-tracer](https://github.com/anthropics/circuit-tracer) — attribution graphs (v0.1.1 backlog)
- [Goodfire SAE releases](https://huggingface.co/Goodfire) — pretrained SAEs
- [Model Context Protocol](https://modelcontextprotocol.io) — host integration spec

## Acknowledgements

Standing on the shoulders of SAELens, TransformerLens, Goodfire's open SAE
releases, and Anthropic's MCP spec.
