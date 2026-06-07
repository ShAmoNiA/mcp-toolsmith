from __future__ import annotations

import json

from typer.testing import CliRunner

from mcp_toolsmith.cli import app

runner = CliRunner()


def test_cli_audit_refuses_python_without_execute(tmp_path):
    marker = tmp_path / "executed.txt"
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        f"""
from pathlib import Path

Path({str(marker)!r}).write_text("executed", encoding="utf-8")


def search_docs(query: str) -> str:
    \"\"\"Search documentation for a specific user question.

    Args:
        query: Question to search for.
    \"\"\"
    return query
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", str(tools_file)])

    assert result.exit_code == 2
    assert "Refusing to execute Python source" in result.output
    assert not marker.exists()


def test_cli_audit_python_execute_opt_in(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
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
    assert "search_docs" in result.output


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

