from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from mcp_toolsmith.introspection import _first_docstring_paragraph, _parse_param_descriptions
from mcp_toolsmith.models import ToolSchema


def load_static_tool_schemas(path: str | Path) -> list[ToolSchema]:
    """Discover @tool-decorated functions without importing Python source."""

    source_path = Path(path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    tools: list[ToolSchema] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        decorator = _tool_decorator(node.decorator_list)
        if decorator is None:
            continue

        docstring = ast.get_docstring(node, clean=True) or ""
        param_descriptions = _parse_param_descriptions(docstring)
        input_schema, metadata = _schema_from_function_def(node, param_descriptions)
        tool_name = decorator.get("name") or node.name
        tool_description = decorator.get("description") or _first_docstring_paragraph(docstring)

        tools.append(
            ToolSchema(
                name=tool_name,
                description=tool_description,
                input_schema=input_schema,
                source=f"{source_path}:{node.lineno}:{node.col_offset + 1}",
                source_kind="function",
                metadata=metadata,
            )
        )
    return tools


def _tool_decorator(decorators: list[ast.expr]) -> dict[str, str | None] | None:
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if not _is_tool_reference(target):
            continue
        metadata: dict[str, str | None] = {"name": None, "description": None}
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg in {"name", "description"} and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, str):
                        metadata[keyword.arg] = value
        return metadata
    return None


def _is_tool_reference(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "tool"
    if isinstance(node, ast.Attribute):
        return node.attr == "tool" and _is_mcp_toolsmith_reference(node.value)
    return False


def _is_mcp_toolsmith_reference(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "mcp_toolsmith"


def _schema_from_function_def(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    param_descriptions: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    unknown_annotations: list[str] = []
    missing_annotations: list[str] = []
    variadic_parameters: list[str] = []

    positional = [*node.args.posonlyargs, *node.args.args]
    positional_defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    for parameter, default_node in zip(positional, positional_defaults, strict=True):
        _add_parameter(
            parameter,
            default_node,
            properties,
            required,
            param_descriptions,
            unknown_annotations,
            missing_annotations,
        )

    for parameter, default_node in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
        _add_parameter(
            parameter,
            default_node,
            properties,
            required,
            param_descriptions,
            unknown_annotations,
            missing_annotations,
        )

    if node.args.vararg is not None:
        variadic_parameters.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        variadic_parameters.append(node.args.kwarg.arg)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    metadata: dict[str, Any] = {"static": True}
    if unknown_annotations:
        metadata["static_unknown_annotations"] = unknown_annotations
    if missing_annotations:
        metadata["static_missing_annotations"] = missing_annotations
    if variadic_parameters:
        metadata["static_variadic_parameters"] = variadic_parameters
    return schema, metadata


def _add_parameter(
    parameter: ast.arg,
    default_node: ast.expr | None,
    properties: dict[str, dict[str, Any]],
    required: list[str],
    param_descriptions: dict[str, str],
    unknown_annotations: list[str],
    missing_annotations: list[str],
) -> None:
    if parameter.annotation is None:
        property_schema: dict[str, Any] = {}
        missing_annotations.append(parameter.arg)
    else:
        annotation = ast.unparse(parameter.annotation)
        property_schema, known = _schema_from_annotation(annotation)
        if not known:
            unknown_annotations.append(parameter.arg)

    if parameter.arg in param_descriptions:
        property_schema["description"] = param_descriptions[parameter.arg]

    if default_node is None:
        required.append(parameter.arg)
    else:
        try:
            property_schema["default"] = ast.literal_eval(default_node)
        except (ValueError, TypeError):
            pass

    properties[parameter.arg] = property_schema


def _schema_from_annotation(annotation: str) -> tuple[dict[str, Any], bool]:
    normalized = annotation.replace("typing.", "")
    simple = {
        "str": {"type": "string"},
        "int": {"type": "integer"},
        "float": {"type": "number"},
        "bool": {"type": "boolean"},
        "dict": {"type": "object"},
        "list": {"type": "array"},
    }
    if normalized in simple:
        return dict(simple[normalized]), True

    if normalized.startswith(("list[", "List[")) and normalized.endswith("]"):
        inner = normalized[5:-1]
        item_schema, known = _schema_from_annotation(inner)
        schema: dict[str, Any] = {"type": "array"}
        if known:
            schema["items"] = item_schema
        return schema, known

    return {}, False
