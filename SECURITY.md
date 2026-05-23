# Security policy

`saegate` is an **advisory** tool. It does not provide a security boundary
and must not be relied on as one. Run untrusted agents in a sandbox
regardless of saegate's verdict.

## Scope

In scope:
- Crashes, hangs, or fail-open paths in the gate, probe, policy, or MCP
  server (any code path that returns `allow` when policy or probe failure
  should have caused `escalate`).
- Secret leakage in logs, telemetry, error messages, or CI artifacts.
- Path-traversal, command-injection, or unsafe deserialization in any CLI
  or MCP handler.

Out of scope:
- Inspector LM "false negatives" or "false positives" relative to subjective
  notions of agent misbehavior — saegate is a behavioral surrogate, not a
  classifier with calibrated accuracy.
- Decisions made by the host on top of an advisory verdict.

## Reporting

Open a GitHub Security Advisory at
<https://github.com/hinanohart/saegate/security/advisories/new>, or open a
regular issue if the report is non-sensitive.

Please include:
- saegate version (`saegate version`)
- minimal reproducer
- expected vs. observed behavior
- whether you believe the failure mode is fail-open or fail-closed

## Supported versions

| Version  | Supported |
|----------|-----------|
| 0.0.x    | yes (current scaffold) |

Older versions are not maintained.

## Telemetry & privacy

- Telemetry is **off by default**.
- When enabled (`SAEGATE_TELEMETRY=on`), only the SHA-256 of the inspector
  prompt is recorded, never the raw text. Records stay on local disk under
  `~/.saegate/`.
- No network calls. No third-party telemetry sinks.
