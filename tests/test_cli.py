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
