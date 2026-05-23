# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) (subset).
Versioning: [PEP 440](https://peps.python.org/pep-0440/).

## [Unreleased]

### Planned
- v0.1.0: real-inference smoke (Llama-3.1-8B + Goodfire SAE l19 on GPU);
  8-scenario calibration harness; PyPI release.
- v0.1.0.post1: post-audit hotfix sweep (3-agent audit per R14 mini).
- v0.1.1: `circuit-tracer` attribution graph as advisory context;
  multi-source SAE registry (Llama Scope, Gemma Scope, custom).
- v0.2: SSM SAE plug-in via `recurrentlens`; HF Space demo; latency
  benchmark; first PyPI publish.
- v1.0: `SAEBench-Gate` eval suite; `subjunctor` PRM cross-link;
  paper-style README; arXiv preprint draft.

## [0.0.1.post2] - 2026-05-24

Second hardening pass (synthesizes three independent post-post1 audits:
architect compliance / critic deep-flaw probe / verifier finding-trace).
No breaking API change.

### Fixed
- `MockProbe` now uses `hashlib.sha256` instead of Python's built-in
  `hash()`. With `PYTHONHASHSEED=random` (the default for `python3`),
  `hash()` is salted per process and the mock probe was therefore
  **not** cross-process deterministic, contradicting its own docstring
  and the README's "deterministic CI" claim. Activations are now stable
  across processes, machines, and Python versions. New regression test
  `test_mock_probe_is_cross_process_deterministic` pins this via
  `subprocess.run`.
- `Gate.check` sandbox-absence handling now normalizes **every** verdict
  (including a strict-mode `deny`) to `escalate`, not just `allow`.
  Sandbox absence is the strongest fail-closed signal — a host that
  special-cases `deny` ("block this tool only") could previously miss
  it. New test `test_sandbox_required_demotes_deny_to_escalate` covers
  the strict+deny case.
- `ToolCall.name` validator now rejects all C0 control characters
  (0x00–0x1F) and DEL (0x7F), not just `\n`/`\r`. A NUL byte in the
  tool name could splice tokens inside the inspector's XML attribute
  frame and corrupt JSONL telemetry. Old behavior accepted those bytes
  silently. New test `test_tool_name_rejects_control_chars`.

### Added
- `tests/test_smoke.py::test_policy_strict_mode_keeps_deny_when_sandboxed`
  — strict mode + sandbox satisfied path was implemented but had no
  dedicated test (caught by deep-flaw audit).
- `mcp_server.build_gate` now logs a `catalog_layer_mismatch` warning
  when the catalog's `layer` disagrees with the probe's `sae_layer`.
  Non-fatal because multi-layer probes are still emergent.
- README OpenHands wiring now includes a concrete `config.toml` MCP
  stdio snippet (previously prose-only).

### Documented
- Dependency upper-bound loosening rationale for v0.0.1: the architecture
  spec pinned `structlog<25`, `transformer-lens==2.9.*`, `sae-lens==5.5.*`,
  but the build environment shipped `structlog 25.5.0` system-wide. The
  pins were widened to `structlog<26`, `transformer-lens>=2.9,<3`,
  `sae-lens>=5.5,<6` so the package installs cleanly. v0.1.0 will
  re-tighten after the calibration eval is run against pinned versions.
- `mcp_server.handle_explain_decision` docstring now explicitly states it
  is non-gating; errors surface as JSON-error responses, not ESCALATE
  Decisions (the gate path remains the only fail-closed surface).

### Not changed (deferred)
- JSON-quote double-escape inside the inspector prompt (critic M-3,
  MEDIUM): switching to a CDATA / base64 envelope for `tool_args` would
  change the rendered prompt structure. Defer to v0.1.0 where the
  calibration eval can pin the inspector LM's behavior on both layouts.
- `check_no_secrets.sh` README/SECURITY whole-file exclusion replaced
  with marker-based gating: low real-world risk (manual review of the
  two affected files in PR reviews), and the marker scheme touches the
  pre-commit and CI surface. Defer to v0.1.0 alongside other gate
  refactors.
- Quickstart contrasting allow-vs-escalate demo (verifier B-MAJ-3
  partial): honesty gap is closed (`README` already says escalate is
  the expected wiring-test result with placeholder feature IDs); UX gap
  remains. Defer to v0.1.0 where the calibrated catalog can ship at
  least one real escalation path.

## [0.0.1.post1] - 2026-05-23

Honest-marketing patch (synthesizes three independent post-Phase-0 audits:
verifier / critic / meta-critic — none of which had read each other's
output at evaluation time). No breaking API change.

### Fixed
- README now states the verdict surface as `allow | escalate` and notes
  that `deny` is only returned when a policy explicitly opts in
  (`mode: strict` + `on_trigger: deny`). The old wording suggested deny
  was a default verdict, which contradicted the policy defaults.
- README "Wiring into a host" now ships concrete MCP client JSON config
  for Claude Code, Cursor, and OpenHands. The previous version was
  Python pseudocode only and did not show how to actually register the
  server.
- README installation now includes `pre-commit install` so contributors
  get the local hooks the CI runs.
- `policy.Policy` class docstring now defines `strict` vs `advisory` mode
  semantics. v0.0.1 had `mode: strict` accepted by the loader but with
  no documented behavior.
- `render_inspector_prompt` now XML-escapes user-controlled input. An
  adversarial draft like `</draft><tool_call name="evil">…` could
  previously inject a synthetic tool-call frame into the inspector
  prompt. New test pins this.
- CHANGELOG / README test-count claims aligned with the actual pytest
  collection count (28 tests after this patch, 26 prior).

### Added
- `tests/test_smoke.py::test_gate_fail_closed_on_probe_timeout` — the
  PROBE_TIMEOUT fail-closed branch was implemented in v0.0.1 but had no
  dedicated test.
- `tests/test_smoke.py::test_render_inspector_prompt_escapes_injection`
  — regression test for the XML-injection fix above.
- README explicit "latency targets are unverified on real inference"
  note. The 500 ms p95 / 700 ms timeout budgets in the architecture are
  unverified on GPU; v0.0.1 only verifies gate overhead with the mock
  probe (< 100 ms).

### Not changed (deferred)
- Goodfire SAE feature catalog still ships zero opinionated entries.
  Calibrated feature IDs land in v0.1.0 with the real-inference smoke.
- Real SAE inference is implemented but not exercised in CI (no GPU).
- The `mcp_server.serve_stdio_json` newline-delimited JSON fallback is
  retained for local diagnosis when the optional `mcp` package is
  missing. Documented in the module docstring; not an MCP-spec wire
  format.

## [0.0.1] - 2026-05-23

### Added
- Phase 0 scaffold: `schemas`, `gate`, `policy`, `probe`
  (`SAEProbe` + `MockProbe`), `features`, `mcp_server`, `telemetry`, `cli`.
- 26 collected pytest tests (20 test functions, some parametrized)
  covering allow / escalate / fail-closed (probe load + runtime errors) /
  sandbox / JSON round-trip / policy validation / telemetry / latency
  overhead / MCP roundtrip.
- `honest_marketing_gate.py` + `check_no_secrets.sh` + pre-commit config.
- CI: ruff lint + format, no-secrets, honest-marketing, pytest on Python
  3.11 + 3.12.
- `configs/policy.example.yaml` + `configs/catalog.example.yaml` with
  placeholder feature IDs (no opinionated defaults).
- License notice (`NOTICE.md`) documenting the Llama 3.1 Community
  License inheritance for the default SAE.
