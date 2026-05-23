"""typer CLI: `saegate serve | probe-once | check-policy | version`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from saegate import __version__
from saegate.features import load_catalog
from saegate.gate import Gate, GateConfig
from saegate.mcp_server import ServerConfig, serve_mcp
from saegate.policy import load_policy
from saegate.probe import MockProbe, ProbeConfig
from saegate.schemas import Draft, ToolCall

app = typer.Typer(
    name="saegate",
    no_args_is_help=True,
    add_completion=False,
    help="Advisory MCP gate via Llama-3.1-8B SAE inspector. Observation only.",
)


@app.command(name="version")
def cmd_version() -> None:
    typer.echo(f"saegate {__version__}")


@app.command(name="check-policy")
def cmd_check_policy(
    policy_path: Path = typer.Argument(..., exists=True, readable=True),
    catalog_path: Path | None = typer.Option(None, "--catalog", "-c", exists=True),
) -> None:
    policy = load_policy(policy_path)
    catalog = load_catalog(catalog_path) if catalog_path else None
    typer.echo(f"policy mode: {policy.mode}")
    typer.echo(f"rules: {len(policy.rules)}")
    for r in policy.rules:
        typer.echo(
            f"  - feature_id={r.feature_id} threshold={r.threshold} on_trigger={r.on_trigger.value} label={r.label!r}"
        )
    if catalog:
        typer.echo(f"catalog: {len(catalog.entries)} entries, layer={catalog.layer}")


@app.command(name="probe-once")
def cmd_probe_once(
    policy_path: Path = typer.Argument(..., exists=True, readable=True),
    tool_name: str = typer.Option(..., "--tool", "-t"),
    arguments_json: str = typer.Option("{}", "--args", "-a"),
    draft: str = typer.Option("", "--draft", "-d"),
    sandboxed: bool = typer.Option(False, "--sandboxed/--no-sandboxed"),
    mock: bool = typer.Option(
        True,
        "--mock/--real",
        help="Use MockProbe (CPU, default) or real SAEProbe (needs [inference] extras).",
    ),
) -> None:
    try:
        args = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        typer.echo(f"invalid --args JSON: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    policy = load_policy(policy_path)
    probe_cfg = ProbeConfig()
    if mock:
        probe = MockProbe(probe_cfg)
    else:
        from saegate.probe import SAEProbe

        probe = SAEProbe(probe_cfg)
    gate = Gate(
        policy=policy,
        probe=probe,
        config=GateConfig(use_mock_probe=mock),
    )
    decision = gate.check(
        ToolCall(name=tool_name, arguments=args),
        Draft(text=draft),
        sandboxed=sandboxed,
    )
    sys.stdout.write(decision.model_dump_json(indent=2) + "\n")


@app.command(name="serve")
def cmd_serve(
    policy_path: Path = typer.Argument(..., exists=True, readable=True),
    catalog_path: Path | None = typer.Option(None, "--catalog", "-c", exists=True),
    mock: bool = typer.Option(
        True,
        "--mock/--real",
        help="Use MockProbe (CPU, default) or real SAEProbe (needs [inference] extras).",
    ),
    sandbox_required: bool = typer.Option(True, "--sandbox-required/--no-sandbox-required"),
) -> None:
    cfg = ServerConfig(
        policy_path=policy_path,
        catalog_path=catalog_path,
        use_mock_probe=mock,
        sandbox_required=sandbox_required,
    )
    serve_mcp(cfg)


if __name__ == "__main__":
    app()
