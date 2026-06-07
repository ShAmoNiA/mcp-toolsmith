from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from mcp_toolsmith import UnsafePythonExecutionError, compile_file, compile_tool


class SearchDocsInput(BaseModel):
    """Search project documentation by natural language query."""

    query: str = Field(description="Question or topic to search for.")
    limit: int = Field(default=5, description="Maximum number of results.")


class CreateTicket(BaseModel):
    """Create a support ticket for a user issue."""

    title: str = Field(description="Ticket title")
    body: str = Field(description="Ticket body")


class KeywordFields(BaseModel):
    """Create a record with JSON Schema keyword-like field names."""

    title: str = Field(description="Title field")
    description: str = Field(description="Description field")
    type: str = Field(description="Type field")
    properties: str = Field(description="Properties field")
    required: str = Field(description="Required field")


def test_compile_file_to_mcp_discovers_function(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
from mcp_toolsmith import tool


@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City and country, such as Madrid, Spain.
        unit: Temperature unit to return.
    """
    return "sunny"
''',
        encoding="utf-8",
    )

    tools = compile_file(tools_file, target="mcp", execute=True)

    assert tools == [
        {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City and country, such as Madrid, Spain.",
                    },
                    "unit": {
                        "default": "celsius",
                        "type": "string",
                        "description": "Temperature unit to return.",
                    },
                },
                "required": ["city"],
                "additionalProperties": False,
            },
        }
    ]


def test_compile_file_supports_decorated_tools(tmp_path):
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        '''
from mcp_toolsmith import tool


@tool(name="search_project_docs", description="Search project docs and return matching document IDs.")
def search_docs(query: str, limit: int = 5) -> list[str]:
    """Search project documentation by natural language query.

    Args:
        query: Question or topic to search for.
        limit: Maximum number of results to return.
    """
    return []


def normalize_query(query: str) -> str:
    """Normalize helper input."""
    return query.strip().lower()
''',
        encoding="utf-8",
    )

    tools = compile_file(tools_file, target="mcp", execute=True)

    assert len(tools) == 1
    assert tools[0]["name"] == "search_project_docs"
    assert tools[0]["description"] == "Search project docs and return matching document IDs."
    assert set(tools[0]["inputSchema"]["properties"]) == {"query", "limit"}


def test_compile_file_all_public_keeps_legacy_public_function_discovery(tmp_path):
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

    tools = compile_file(tools_file, target="mcp", execute=True, all_public=True)

    assert [tool["name"] for tool in tools] == ["normalize_query"]


def test_compile_tool_to_openai_accepts_pydantic_model():
    tool = compile_tool(SearchDocsInput, target="openai")

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "SearchDocsInput"
    assert tool["function"]["parameters"]["properties"]["query"]["description"] == (
        "Question or topic to search for."
    )


def test_mcp_compile_shape(tmp_path):
    tools_file = _write_json_tool(tmp_path)

    tools = compile_file(tools_file, target="mcp")

    assert tools == [
        {
            "name": "search_docs",
            "description": "Search documents by query and return matching document IDs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    ]


def test_openai_compile_shape(tmp_path):
    tools_file = _write_json_tool(tmp_path)

    tools = compile_file(tools_file, target="openai")

    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "search_docs",
                "description": "Search documents by query and return matching document IDs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query.",
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_compile_file_refuses_python_without_execute_and_does_not_run_top_level_code(tmp_path):
    marker = tmp_path / "executed.txt"
    tools_file = tmp_path / "tools.py"
    tools_file.write_text(
        f"""
from pathlib import Path

Path({str(marker)!r}).write_text("executed", encoding="utf-8")


def get_weather(city: str) -> str:
    \"\"\"Get current weather for a city.

    Args:
        city: City and country.
    \"\"\"
    return "sunny"
""",
        encoding="utf-8",
    )

    with pytest.raises(UnsafePythonExecutionError):
        compile_file(tools_file, target="mcp")

    assert not marker.exists()


def test_compiler_preserves_property_named_title():
    compiled = compile_tool(CreateTicket, target="mcp")
    props = compiled["inputSchema"]["properties"]

    assert "title" in props
    assert "body" in props
    assert set(compiled["inputSchema"]["required"]) == {"title", "body"}


def test_compiler_preserves_keyword_like_property_names():
    compiled = compile_tool(KeywordFields, target="mcp")
    props = compiled["inputSchema"]["properties"]

    assert {"title", "description", "type", "properties", "required"} <= set(props)
    assert set(compiled["inputSchema"]["required"]) == {
        "title",
        "description",
        "type",
        "properties",
        "required",
    }


def test_compiler_rejects_required_fields_missing_from_properties():
    with pytest.raises(ValueError, match="required fields missing from properties"):
        compile_tool(
            {
                "name": "bad_tool",
                "description": "Demonstrate an invalid required field mismatch.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": ["missing"],
                },
            },
            target="mcp",
        )


def _write_json_tool(tmp_path):
    tools_file = tmp_path / "tools.json"
    tools_file.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "name": "search_docs",
                        "description": "Search documents by query and return matching document IDs.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query.",
                                }
                            },
                            "required": ["query"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return tools_file
