"""MCP server unit tests (stdio JSON fallback mode, no mcp dep required)."""

from __future__ import annotations

import io
import json
import sys

import yaml

from saegate.features import load_catalog
from saegate.gate import Gate, GateConfig
from saegate.mcp_server import (
    ServerConfig,
    build_gate,
    decision_to_dict,
    handle_explain_decision,
    handle_gate_check,
    handle_list_features,
    serve_stdio_json,
)
from saegate.policy import load_policy
from saegate.probe import MockProbe


def _write_policy(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "mode": "advisory",
                "rules": [
                    {
                        "feature_id": 1,
                        "label": "demo",
                        "threshold": 0.0,
                        "on_trigger": "escalate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return p


def _write_catalog(tmp_path):
    p = tmp_path / "catalog.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "sae_model_id": "Goodfire/Llama-3.1-8B-Instruct-SAE-l19",
                "layer": 19,
                "entries": [
                    {
                        "feature_id": 1,
                        "label": "demo",
                        "source": "test",
                        "suggested_threshold": 0.5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_build_gate_round_trip(tmp_path) -> None:
    policy_path = _write_policy(tmp_path)
    catalog_path = _write_catalog(tmp_path)
    cfg = ServerConfig(
        policy_path=policy_path,
        catalog_path=catalog_path,
        use_mock_probe=True,
        sandbox_required=False,
    )
    gate, catalog = build_gate(cfg)
    assert isinstance(gate, Gate)
    assert catalog is not None
    assert len(catalog.entries) == 1


def test_handle_gate_check(tmp_path) -> None:
    policy = load_policy(_write_policy(tmp_path))
    gate = Gate(
        policy=policy,
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    payload = handle_gate_check(
        gate,
        {"tool_name": "read_file", "arguments": {"path": "README.md"}},
    )
    assert payload["verdict"] in ("allow", "deny", "escalate")
    assert "reasons" in payload
    assert "activations" in payload


def test_handle_list_features(tmp_path) -> None:
    catalog = load_catalog(_write_catalog(tmp_path))
    payload = handle_list_features(catalog)
    assert payload["layer"] == 19
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["feature_id"] == 1


def test_handle_explain_decision(tmp_path) -> None:
    policy = load_policy(_write_policy(tmp_path))
    gate = Gate(
        policy=policy,
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    from saegate.schemas import ToolCall

    decision = gate.check(ToolCall(name="bash", arguments={"cmd": "ls"}))
    text = handle_explain_decision(gate, decision_to_dict(decision))
    assert "verdict:" in text
    assert "advisory only" in text


def test_serve_stdio_json_roundtrip(tmp_path, monkeypatch) -> None:
    policy = load_policy(_write_policy(tmp_path))
    catalog = load_catalog(_write_catalog(tmp_path))
    gate = Gate(
        policy=policy,
        probe=MockProbe(),
        config=GateConfig(use_mock_probe=True, sandbox_required=False),
    )
    request = (
        json.dumps(
            {
                "method": "gate_check",
                "params": {"tool_name": "bash", "arguments": {"cmd": "ls"}},
            }
        )
        + "\n"
        + json.dumps({"method": "list_features"})
        + "\n"
        + json.dumps({"method": "bogus_method"})
        + "\n"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(request))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    try:
        serve_stdio_json(gate, catalog)
    finally:
        monkeypatch.setattr("sys.stdout", sys.__stdout__)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3
    assert "verdict" in json.loads(lines[0])
    assert "entries" in json.loads(lines[1])
    assert "error" in json.loads(lines[2])
