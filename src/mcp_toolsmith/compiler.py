from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from jsonschema.validators import Draft202012Validator
from pydantic import BaseModel

from mcp_toolsmith.introspection import (
    function_to_tool_schema,
    load_tool_schemas,
    mcp_definition_to_tool_schema,
    pydantic_model_to_tool_schema,
)
from mcp_toolsmith.models import ToolSchema

Target = Literal["mcp", "openai"]


def compile_file(
    path: str | Path,
    target: Target = "mcp",
    *,
    execute: bool = False,
) -> list[dict[str, Any]]:
    """Compile all tools discovered in a Python or MCP JSON file."""

    return compile_tools(load_tool_schemas(path, execute_python=execute), target=target)


def compile_tool(
    tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any],
    target: Target = "mcp",
) -> dict[str, Any]:
    """Compile one tool-like object into a provider-specific definition."""

    return _compile_one(_coerce_tool_schema(tool), target=target)


def compile_tools(tools: list[ToolSchema], target: Target = "mcp") -> list[dict[str, Any]]:
    """Compile provider-neutral tool schemas into MCP or OpenAI definitions."""

    if target not in {"mcp", "openai"}:
        raise ValueError("target must be one of: mcp, openai")
    return [_compile_one(tool, target=target) for tool in tools]


def _coerce_tool_schema(tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any]) -> ToolSchema:
    if isinstance(tool, ToolSchema):
        return tool
    if isinstance(tool, dict):
        return mcp_definition_to_tool_schema(tool)
    if isinstance(tool, type) and issubclass(tool, BaseModel):
        return pydantic_model_to_tool_schema(tool)
    if callable(tool):
        return function_to_tool_schema(tool)
    raise TypeError("tool must be a ToolSchema, function, Pydantic model, or MCP definition dict")


def _compile_one(tool: ToolSchema, target: Target) -> dict[str, Any]:
    schema = _provider_schema(tool.input_schema)
    if target == "mcp":
        return {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": schema,
        }
    if target == "openai":
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            },
        }
    raise ValueError("target must be one of: mcp, openai")


def _provider_schema(schema: dict[str, Any]) -> dict[str, Any]:
    compiled = copy.deepcopy(schema)
    _remove_json_schema_noise(compiled)
    if compiled.get("type") == "object":
        compiled.setdefault("additionalProperties", False)
    Draft202012Validator.check_schema(compiled)
    _validate_required_properties_exist(compiled)
    return compiled


def _remove_json_schema_noise(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("title", None)
        for key in list(node):
            value = node[key]
            if key == "description" and value == "":
                node.pop(key)
                continue
            if key == "properties" and isinstance(value, dict):
                for property_schema in value.values():
                    _remove_json_schema_noise(property_schema)
                continue
            _remove_json_schema_noise(value)
    elif isinstance(node, list):
        for item in node:
            _remove_json_schema_noise(item)


def _validate_required_properties_exist(schema: dict[str, Any]) -> None:
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    if isinstance(required, list) and isinstance(properties, dict):
        missing = sorted(set(required) - set(properties))
        if missing:
            raise ValueError(f"Schema has required fields missing from properties: {missing}")
