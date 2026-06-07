from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from mcp_toolsmith.auditor import audit_file
from mcp_toolsmith.compiler import compile_file

app = typer.Typer(help="Audit and compile Python tool schemas for LLM agents.", no_args_is_help=True)
console = Console()

ToolFileArgument = Annotated[
    Path,
    typer.Argument(exists=True, readable=True, help="Python or MCP JSON tool file."),
]
JsonOutputOption = Annotated[
    bool,
    typer.Option("--json", help="Emit a machine-readable JSON report."),
]
TargetOption = Annotated[
    Literal["mcp", "openai"],
    typer.Option(help="Output target."),
]
ExecuteOption = Annotated[
    bool,
    typer.Option("--execute", help="Execute trusted Python files to discover decorated tools."),
]
AllPublicOption = Annotated[
    bool,
    typer.Option("--all-public", help="Discover every public top-level function and Pydantic model."),
]


@app.command()
def audit(
    path: ToolFileArgument,
    json_output: JsonOutputOption = False,
    execute: ExecuteOption = False,
    all_public: AllPublicOption = False,
) -> None:
    """Audit Python functions, Pydantic models, or MCP tool definitions."""

    try:
        report = audit_file(path, execute=execute, all_public=all_public)
    except Exception as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if json_output:
        console.print_json(data=report.as_dict())
    else:
        console.print(report)
    if report.error_count:
        raise typer.Exit(code=1)


@app.command(name="compile")
def compile_command(
    path: ToolFileArgument,
    target: TargetOption = "mcp",
    execute: ExecuteOption = False,
    all_public: AllPublicOption = False,
) -> None:
    """Compile discovered tools into provider-specific schemas."""

    try:
        output = compile_file(path, target=target, execute=execute, all_public=all_public)
    except Exception as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print_json(data=output)


if __name__ == "__main__":
    app()
