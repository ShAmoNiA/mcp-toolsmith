from __future__ import annotations

import json

from typer.testing import CliRunner

from mcp_toolsmith.cli import app

runner = CliRunner()


def test_cli_audit_python_uses_static_mode_without_execute(tmp_path):
    marker = tmp_path / "executed.txt"
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        f"""
from mcp_toolsmith import tool
from pathlib import Path


@tool
def search_docs(query: str) -> str:
    \"\"\"Search documentation for a specific user question.

    Args:
        query: Question to search for.
    \"\"\"
    return query


Path({str(marker)!r}).write_text("executed", encoding="utf-8")
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file)])

    assert result.exit_code == 0
    assert "Mode: static" in result.output
    assert "search_docs" in result.output
    assert not marker.exists()


def test_cli_audit_python_execute_opt_in(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
from mcp_toolsmith import tool


@tool
def search_docs(query: str) -> str:
    """Search documentation for a specific user question.

    Args:
        query: Question to search for.
    """
    return query
''',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file), "--execute"])

    assert result.exit_code == 0
    assert "Mode: execute" in result.output
    assert "search_docs" in result.output


def test_cli_audit_python_execute_ignores_public_helpers_by_default(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
def normalize_query(query: str) -> str:
    """Normalize helper input."""
    return query.strip().lower()
''',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file), "--execute"])

    assert result.exit_code == 0
    assert "No tools were discovered" in result.output
    assert "normalize_query" not in result.output


def test_cli_audit_static_no_decorated_tools_suggests_execute_all_public(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
def normalize_query(query: str) -> str:
    """Normalize helper input."""
    return query.strip().lower()
''',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file)])

    assert result.exit_code == 0
    assert "No @tool-decorated functions were discovered" in result.output
    assert "use --execute --all-public for trusted files" in result.output


def test_cli_audit_all_public_discovers_public_helpers(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
def normalize_query(query: str) -> str:
    """Normalize helper input.

    Args:
        query: Query to normalize.
    """
    return query.strip().lower()
''',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file), "--execute", "--all-public"])

    assert result.exit_code == 0
    assert "normalize_query" in result.output


def test_cli_compile_json_without_execute(tmp_path):
    tools_file = tmp_path / "tools.json"
    tools_file.write_text(
        json.dumps(
            {
                "name": "search_docs",
                "description": "Search documentation for a specific user question.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Question or topic to search for.",
                        }
                    },
                    "required": ["query"],
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["compile", str(tools_file), "--target", "openai"])

    assert result.exit_code == 0
    assert '"type": "function"' in result.output


def test_cli_audit_fail_on_warning_exits_1(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
from mcp_toolsmith import tool


@tool
def search_docs(query: str) -> str:
    """Search docs."""
    return query
''',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file), "--fail-on", "warning"])

    assert result.exit_code == 1
    assert "Warnings:" in result.output


def test_cli_audit_json_includes_profile(tmp_path):
    tools_file = tmp_path / "tools.json"
    tools_file.write_text(
        json.dumps(
            {
                "name": "run",
                "description": "Run task.",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file), "--profile", "openai", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["profile"] == "openai"
    assert any(finding["rule_id"] == "openai.name.vague" for finding in payload["warnings"])


def test_cli_audits_directory_with_locations_and_exclusions(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "tools.py").write_text(
        '''
from mcp_toolsmith import tool


@tool
def search_docs(query: str) -> str:
    """Search documentation for a specific user question."""
    return query
''',
        encoding="utf-8",
    )
    excluded = tmp_path / "tests"
    excluded.mkdir()
    (excluded / "bad.py").write_text("this is not python", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "web-app", "scripts": {}}', encoding="utf-8")
    generated = tmp_path / "build"
    generated.mkdir()
    (generated / "bad.py").write_text("this is not python", encoding="utf-8")

    result = runner.invoke(app, ["audit", str(tmp_path), "--exclude", "tests/**", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["file_count"] == 1
    assert payload["mode"] == "project"
    finding = next(item for item in payload["warnings"] if item["code"] == "schema.arg_description_missing")
    assert finding["path"].endswith("tools.py")
    assert finding["line"] == 6
    assert finding["column"] == 1

    text_result = runner.invoke(app, ["audit", str(tmp_path), "--exclude", "tests/**"])
    assert f"{source / 'tools.py'}:6:1" in text_result.output


def test_cli_uses_pyproject_config_and_specific_suppression(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.mcp-toolsmith]
profile = "openai"
fail-on = "warning"
include = ["src/**/*.py"]
ignore = ["schema.arg_description_missing"]
max-schema-depth = 4

[[tool.mcp-toolsmith.per-file-ignores]]
path = "src/generated/**"
rules = ["description.too_short"]
""",
        encoding="utf-8",
    )
    source = tmp_path / "src"
    source.mkdir()
    (source / "tools.py").write_text(
        '''
from mcp_toolsmith import tool

@tool
def search_docs(query: str) -> str:
    """Search docs."""
    return query
''',
        encoding="utf-8",
    )
    (tmp_path / "ignored.py").write_text("not valid python", encoding="utf-8")

    result = runner.invoke(app, ["audit", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["profile"] == "openai"
    assert payload["file_count"] == 1
    assert not any(item["code"] == "schema.arg_description_missing" for item in payload["warnings"])


def test_cli_options_override_pyproject_values(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mcp-toolsmith]\nprofile = "openai"\nfail-on = "warning"\n',
        encoding="utf-8",
    )
    tools_file = tmp_path / "tools.json"
    tools_file.write_text(
        json.dumps(
            {
                "name": "search_docs",
                "description": "Search docs.",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["audit", str(tools_file), "--profile", "generic", "--fail-on", "never", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["profile"] == "generic"


def test_config_show_prints_effective_configuration(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mcp-toolsmith]\nprofile = "mcp"\nignore = ["description.too_short"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "Configuration source: pyproject.toml" in result.output
    assert "profile: mcp" in result.output
    assert "- description.too_short" in result.output
