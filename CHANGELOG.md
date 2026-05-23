# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) (subset).
Versioning: [PEP 440](https://peps.python.org/pep-0440/).

## [Unreleased]

### Planned
- v0.1.0: real-inference smoke (Llama-3.1-8B + Goodfire SAE l19 on GPU);
  8-scenario calibration harness; PyPI release;
  branch protection landing.
- v0.1.0.post1: post-audit hotfix sweep (3-agent audit per R14 mini).
- v0.1.1: `circuit-tracer` attribution graph as advisory context;
  multi-source SAE registry (Llama Scope, Gemma Scope, custom).
- v0.2: SSM SAE plug-in via `recurrentlens`; HF Space demo; latency
  benchmark; first PyPI publish.
- v1.0: `SAEBench-Gate` eval suite; `subjunctor` PRM cross-link;
  paper-style README; arXiv preprint draft.

## [0.0.1] - 2026-05-23

### Added
- Phase 0 scaffold: `schemas`, `gate`, `policy`, `probe`
  (`SAEProbe` + `MockProbe`), `features`, `mcp_server`, `telemetry`, `cli`.
- 15+ smoke tests covering allow / escalate / fail-closed / sandbox /
  JSON round-trip / policy validation / telemetry / latency overhead /
  MCP roundtrip.
- `honest_marketing_gate.py` + `check_no_secrets.sh` + pre-commit config.
- CI: ruff lint + format, no-secrets, honest-marketing, pytest on Python
  3.11 + 3.12.
- `configs/policy.example.yaml` + `configs/catalog.example.yaml` with
  placeholder feature IDs (no opinionated defaults).
- License notice (`NOTICE.md`) documenting the Llama 3.1 Community
  License inheritance for the default SAE.

### Not yet
- Real SAE inference is implemented but not exercised in CI (no GPU).
- Feature labelling / calibration is the responsibility of the user.
- MCP stdio server only; HTTP/SSE deferred to v0.2.
