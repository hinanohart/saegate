<!--
Thanks for contributing. Before opening:
  1. `pre-commit run --all-files` passes
  2. `pytest` passes (28+ tests)
  3. Any new claim in README/CHANGELOG passes `scripts/honest_marketing_gate.py`
-->

## Summary

<!-- 1-3 sentences: what changes, why now. -->

## Type of change

- [ ] Bug fix (advisory verdict / reasoning trace correctness)
- [ ] New capability (probe / policy / MCP server / CLI)
- [ ] Documentation / honest-marketing surface
- [ ] Build / CI / dependency
- [ ] Test only

## Honest-marketing self-check

- [ ] No new claim of "guaranteed safety", "complete", "永続的", "完全自動", or similar.
- [ ] Any new public-facing claim is verifiable from code or tests.
- [ ] If this affects the verdict surface (`allow` / `escalate` / `deny`), the README and CHANGELOG agree.

## Verification

<!-- How did you test? Include exact commands + observed Decision JSON if relevant. -->

```text
$ PYTHONPATH=src pytest -q
...
```
