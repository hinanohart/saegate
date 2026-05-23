"""MCP stdio server exposing the gate as tools.

Tools:
    gate_check(tool_name, arguments, draft_text="", sandboxed=False) -> Decision JSON
    list_features() -> [FeatureEntry]
    explain_decision(decision_json) -> str

The `mcp` package is optional. If it is not installed, this module exposes a
plain `serve_stdio_json(...)` fallback that speaks newline-delimited JSON over
stdin/stdout. The fallback is a **diagnosis aid** — it is NOT an MCP-spec
wire format. Production hosts should install `saegate[mcp]` and use the real
MCP stdio path via `serve_mcp(...)`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from saegate.features import FeatureCatalog, load_catalog
from saegate.gate import Gate, GateConfig
from saegate.policy import load_policy
from saegate.probe import MockProbe, ProbeConfig, SAEProbe
from saegate.schemas import Decision, Draft, ToolCall

log = structlog.get_logger("saegate.mcp")


@dataclass
class ServerConfig:
    policy_path: Path | None = None
    catalog_path: Path | None = None
    use_mock_probe: bool = False
    sandbox_required: bool = True


def build_gate(server_cfg: ServerConfig) -> tuple[Gate, FeatureCatalog | None]:
    if server_cfg.policy_path is None:
        raise ValueError("policy_path required")
    policy = load_policy(server_cfg.policy_path)
    catalog: FeatureCatalog | None = None
    if server_cfg.catalog_path is not None:
        catalog = load_catalog(server_cfg.catalog_path)
    probe_cfg = ProbeConfig()
    probe = MockProbe(probe_cfg) if server_cfg.use_mock_probe else SAEProbe(probe_cfg)
    # Warn (do not fail) when catalog.layer disagrees with probe sae_layer:
    # a layer 19 catalog used against a layer 25 probe will silently mis-label
    # activations otherwise. Non-fatal because users may run with a future
    # multi-layer probe and the catalog convention is still emergent.
    if catalog is not None and catalog.layer and catalog.layer != probe_cfg.sae_layer:
        log.warning(
            "mcp.catalog_layer_mismatch",
            catalog_layer=catalog.layer,
            probe_layer=probe_cfg.sae_layer,
        )
    gate_cfg = GateConfig(
        sandbox_required=server_cfg.sandbox_required,
        use_mock_probe=server_cfg.use_mock_probe,
    )
    gate = Gate(policy=policy, probe=probe, config=gate_cfg)
    return gate, catalog


def handle_gate_check(gate: Gate, payload: dict[str, Any]) -> dict[str, Any]:
    tool = ToolCall(
        name=str(payload.get("tool_name", "")),
        arguments=payload.get("arguments", {}) or {},
        server=payload.get("server"),
    )
    draft = Draft(text=str(payload.get("draft_text", "") or ""))
    sandboxed = bool(payload.get("sandboxed", False))
    decision = gate.check(tool, draft, sandboxed=sandboxed)
    return decision_to_dict(decision)


def handle_list_features(catalog: FeatureCatalog | None) -> dict[str, Any]:
    if catalog is None:
        return {"entries": []}
    return {
        "sae_model_id": catalog.sae_model_id,
        "layer": catalog.layer,
        "entries": [
            {
                "feature_id": e.feature_id,
                "label": e.label,
                "source": e.source,
                "suggested_threshold": e.suggested_threshold,
                "note": e.note,
            }
            for e in catalog.entries
        ],
    }


def handle_explain_decision(gate: Gate, payload: dict[str, Any]) -> str:
    """Render a human-readable explanation. Non-gating: errors are surfaced
    by the caller's `try/except` (see `serve_stdio_json` and `_call_tool`),
    not as ESCALATE Decisions."""
    decision = Decision.model_validate(payload)
    return gate.explain(decision)


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    return json.loads(decision.model_dump_json())


def serve_stdio_json(gate: Gate, catalog: FeatureCatalog | None) -> None:
    """Newline-delimited JSON loop over stdin/stdout (no MCP dep required).

    Request format:
        {"method": "gate_check", "params": {...}}
        {"method": "list_features"}
        {"method": "explain_decision", "params": {...}}
    """
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
            method = req.get("method")
            params = req.get("params", {}) or {}
            if method == "gate_check":
                result: Any = handle_gate_check(gate, params)
            elif method == "list_features":
                result = handle_list_features(catalog)
            elif method == "explain_decision":
                result = handle_explain_decision(gate, params)
            else:
                result = {"error": f"unknown method: {method}"}
            sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"error": f"{type(exc).__name__}: {exc}"}) + "\n")
            sys.stdout.flush()


def serve_mcp(server_cfg: ServerConfig) -> None:
    """Real MCP stdio server. Requires `pip install 'saegate[mcp]'`.

    Falls back to serve_stdio_json if the mcp package is not installed (with a
    stderr warning), so the CLI does not crash when the optional dep is missing.
    """
    gate, catalog = build_gate(server_cfg)
    try:
        import mcp  # noqa: F401
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
        from mcp.types import TextContent, Tool  # type: ignore
    except Exception:
        sys.stderr.write(
            "[saegate] mcp package not installed — falling back to JSON-stdio mode.\n"
            "          Install with: pip install 'saegate[mcp]'\n"
        )
        serve_stdio_json(gate, catalog)
        return

    server = Server("saegate")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="gate_check",
                description="Advisory gate check via SAE inspector probe.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object"},
                        "draft_text": {"type": "string"},
                        "sandboxed": {"type": "boolean"},
                    },
                    "required": ["tool_name"],
                },
            ),
            Tool(
                name="list_features",
                description="List candidate SAE features from the catalog.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="explain_decision",
                description="Render a human-readable explanation of a Decision JSON.",
                inputSchema={
                    "type": "object",
                    "properties": {"decision": {"type": "object"}},
                    "required": ["decision"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "gate_check":
                payload = handle_gate_check(gate, arguments)
                text = json.dumps(payload, sort_keys=True)
            elif name == "list_features":
                text = json.dumps(handle_list_features(catalog), sort_keys=True)
            elif name == "explain_decision":
                decision = arguments.get("decision", {})
                text = handle_explain_decision(gate, decision)
            else:
                text = json.dumps({"error": f"unknown tool: {name}"})
        except Exception as exc:
            text = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return [TextContent(type="text", text=text)]

    import asyncio

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
