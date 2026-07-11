from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from mcp_toolsmith.compiler import compile_file
from mcp_toolsmith.configuration import load_config
from mcp_toolsmith.repository import audit_path

app = typer.Typer(help="Audit and compile Python tool schemas for LLM agents.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect mcp-toolsmith configuration.")
app.add_typer(config_app, name="config")
console = Console()

ToolFileArgument = Annotated[
    Path,
    typer.Argument(exists=True, readable=True, file_okay=True, dir_okay=False, help="Python or MCP JSON tool file."),
]
AuditPathArgument = Annotated[
    Path,
    typer.Argument(exists=True, readable=True, help="Python/MCP JSON file or project directory."),
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
    path: AuditPathArgument,
    json_output: JsonOutputOption = False,
    execute: ExecuteOption = False,
    all_public: AllPublicOption = False,
    profile: Annotated[
        Literal["generic", "openai", "mcp"] | None,
        typer.Option("--profile", help="Compatibility profile to audit against."),
    ] = None,
    fail_on: Annotated[
        Literal["error", "warning", "never"] | None,
        typer.Option("--fail-on", help="Which severity should produce exit code 1."),
    ] = None,
    include: Annotated[
        list[str] | None, typer.Option("--include", help="Glob of files to include (repeatable).")
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Glob of files to exclude (repeatable).")
    ] = None,
    ignore: Annotated[list[str] | None, typer.Option("--ignore", help="Rule code to suppress (repeatable).")] = None,
    max_schema_depth: Annotated[int | None, typer.Option("--max-schema-depth", min=1)] = None,
) -> None:
    """Audit Python functions, Pydantic models, or MCP tool definitions."""

    try:
        config = load_config(path)
        effective_profile = profile or config.profile
        effective_fail_on = fail_on or config.fail_on
        report = audit_path(
            path,
            root=config.root,
            include=tuple(include) if include else config.include,
            exclude=(*config.exclude, *(exclude or [])),
            ignore=tuple(ignore) if ignore else config.ignore,
            per_file_ignores=config.per_file_ignores,
            execute=execute,
            all_public=all_public,
            profile=effective_profile,
            max_schema_depth=max_schema_depth or config.max_schema_depth,
        )
    except Exception as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if json_output:
        console.print_json(data=report.as_dict())
    else:
        console.print(report, soft_wrap=True)
    if _should_fail(report.error_count, report.warning_count, effective_fail_on):
        raise typer.Exit(code=1)


@config_app.command("show")
def config_show() -> None:
    """Show the effective configuration for the current project."""

    try:
        config = load_config()
    except Exception as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=2) from exc
    source = config.source.name if config.source else "built-in defaults"
    lines = [
        f"Configuration source: {source}",
        "",
        f"profile: {config.profile}",
        f"fail-on: {config.fail_on}",
        "include:",
        *[f"- {pattern}" for pattern in config.include],
        "exclude:",
        *[f"- {pattern}" for pattern in config.exclude],
        "ignored rules:",
        *([f"- {rule}" for rule in config.ignore] or ["- none"]),
        f"max-schema-depth: {config.max_schema_depth}",
    ]
    console.print("\n".join(lines))


def _should_fail(error_count: int, warning_count: int, fail_on: str) -> bool:
    if fail_on == "never":
        return False
    if fail_on == "warning":
        return error_count > 0 or warning_count > 0
    return error_count > 0


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
