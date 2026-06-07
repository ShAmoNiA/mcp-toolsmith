from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model

from mcp_toolsmith.models import ToolSchema

_GOOGLE_ARGS_HEADER_RE = re.compile(r"^\s*(args|arguments|parameters)\s*:\s*$", re.IGNORECASE)
_GOOGLE_ARG_RE = re.compile(r"^\s{2,}([a-zA-Z_][\w-]*)(?:\s*\([^)]*\))?\s*:\s*(.+)\s*$")
_REST_PARAM_RE = re.compile(r"^\s*:param\s+([a-zA-Z_][\w-]*)\s*:\s*(.+)\s*$")


class UnsafePythonExecutionError(RuntimeError):
    """Raised when a Python file would need to be executed without opt-in."""


def load_tool_schemas(
    path: str | Path,
    *,
    execute_python: bool = False,
    all_public: bool = False,
) -> list[ToolSchema]:
    """Load provider-neutral tool schemas from a Python or JSON file."""

    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    if source_path.suffix.lower() == ".json":
        return _load_json_tool_schemas(source_path)
    if source_path.suffix.lower() != ".py":
        raise ValueError("Only .py and .json inputs are supported")
    if not execute_python:
        raise UnsafePythonExecutionError(
            "Refusing to execute Python source. Use --execute only for trusted files."
        )

    module = _load_module_from_path(source_path)
    tools: list[ToolSchema] = []
    tools.extend(_discover_functions(module, source_path, all_public=all_public))
    if all_public:
        tools.extend(_discover_pydantic_models(module, source_path))
    return tools


def function_to_tool_schema(function: Callable[..., Any], source: str | None = None) -> ToolSchema:
    """Convert a Python function into a provider-neutral tool schema."""

    description = _first_docstring_paragraph(inspect.getdoc(function) or "")
    metadata = getattr(function, "__mcp_toolsmith_tool__", {})
    tool_name = metadata.get("name") or function.__name__
    tool_description = metadata.get("description") or description
    param_descriptions = _parse_param_descriptions(inspect.getdoc(function) or "")
    schema = _schema_from_function(function)

    properties = schema.setdefault("properties", {})
    for param_name, param_description in param_descriptions.items():
        if param_name in properties and "description" not in properties[param_name]:
            properties[param_name]["description"] = param_description

    return ToolSchema(
        name=tool_name,
        description=tool_description,
        input_schema=schema,
        source=source or _callable_source(function),
        source_kind="function",
        metadata={"callable": function},
    )


def pydantic_model_to_tool_schema(model: type[BaseModel], source: str | None = None) -> ToolSchema:
    """Convert a Pydantic v2 model into a provider-neutral tool schema."""

    description = _first_docstring_paragraph(inspect.cleandoc(model.__doc__ or ""))
    schema = model.model_json_schema()
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})

    return ToolSchema(
        name=model.__name__,
        description=description or str(schema.get("description", "")),
        input_schema=schema,
        source=source or _callable_source(model),
        source_kind="pydantic",
        metadata={"model": model},
    )


def mcp_definition_to_tool_schema(definition: dict[str, Any], source: str = "<memory>") -> ToolSchema:
    """Convert an MCP-style tool definition into a provider-neutral tool schema."""

    if "name" not in definition or "inputSchema" not in definition:
        raise ValueError("MCP tool definitions must contain 'name' and 'inputSchema'")

    schema = definition["inputSchema"]
    if not isinstance(schema, dict):
        raise ValueError("MCP tool inputSchema must be an object")

    return ToolSchema(
        name=str(definition["name"]),
        description=str(definition.get("description", "")),
        input_schema=schema,
        source=source,
        source_kind="mcp",
        metadata={"definition": definition},
    )


def _load_module_from_path(path: Path) -> ModuleType:
    module_name = f"_mcp_toolsmith_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import Python file: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def _load_json_tool_schemas(path: Path) -> list[ToolSchema]:
    data = json.loads(path.read_text(encoding="utf-8"))
    definitions = _coerce_json_tool_definitions(data)
    return [
        mcp_definition_to_tool_schema(definition, source=f"{path}:{index}")
        for index, definition in enumerate(definitions)
    ]


def _coerce_json_tool_definitions(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        definitions = data
    elif isinstance(data, dict) and isinstance(data.get("tools"), list):
        definitions = data["tools"]
    elif isinstance(data, dict):
        definitions = [data]
    else:
        raise ValueError("JSON input must be a tool definition, a list, or an object with tools")

    if not all(isinstance(definition, dict) for definition in definitions):
        raise ValueError("Every JSON tool definition must be an object")
    return definitions


def _discover_functions(module: ModuleType, path: Path, *, all_public: bool = False) -> list[ToolSchema]:
    tools: list[ToolSchema] = []
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if not inspect.isfunction(value):
            continue
        if value.__module__ != module.__name__:
            continue
        is_decorated = hasattr(value, "__mcp_toolsmith_tool__")
        if not is_decorated and not all_public:
            continue
        tools.append(function_to_tool_schema(value, source=f"{path}:{name}"))
    return tools


def _discover_pydantic_models(module: ModuleType, path: Path) -> list[ToolSchema]:
    tools: list[ToolSchema] = []
    for name, value in vars(module).items():
        if name.startswith("_") or not inspect.isclass(value):
            continue
        if value.__module__ != module.__name__:
            continue
        if issubclass(value, BaseModel) and value is not BaseModel:
            tools.append(pydantic_model_to_tool_schema(value, source=f"{path}:{name}"))
    return tools


def _schema_from_function(function: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(function)
    try:
        type_hints = get_type_hints(function, include_extras=True)
    except Exception:
        type_hints = {}

    fields: dict[str, tuple[Any, Any]] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            continue
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Signature.empty:
            annotation = Any
        default = ... if parameter.default is inspect.Signature.empty else parameter.default
        fields[parameter.name] = (annotation, default)

    model_name = "".join(part.title() for part in function.__name__.split("_")) + "Params"
    params_model = create_model(model_name, **fields)
    schema = params_model.model_json_schema()
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("additionalProperties", False)
    return schema


def _first_docstring_paragraph(docstring: str) -> str:
    if not docstring:
        return ""

    lines: list[str] = []
    for line in inspect.cleandoc(docstring).splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if _GOOGLE_ARGS_HEADER_RE.match(stripped) or stripped.lower() in {"returns:", "raises:"}:
            break
        if stripped.startswith(":param "):
            break
        lines.append(stripped)
    return " ".join(lines)


def _parse_param_descriptions(docstring: str) -> dict[str, str]:
    if not docstring:
        return {}

    descriptions: dict[str, str] = {}
    cleaned = inspect.cleandoc(docstring)

    for line in cleaned.splitlines():
        rest_match = _REST_PARAM_RE.match(line)
        if rest_match:
            descriptions[rest_match.group(1)] = rest_match.group(2).strip()

    in_args = False
    current_name: str | None = None
    for line in cleaned.splitlines():
        if _GOOGLE_ARGS_HEADER_RE.match(line):
            in_args = True
            current_name = None
            continue
        if in_args and line.strip().endswith(":") and not line.startswith((" ", "\t")):
            break
        if not in_args:
            continue

        arg_match = _GOOGLE_ARG_RE.match(line)
        if arg_match:
            current_name = arg_match.group(1)
            descriptions[current_name] = arg_match.group(2).strip()
            continue
        if current_name and line.startswith(("    ", "\t")) and line.strip():
            descriptions[current_name] += " " + line.strip()

    return descriptions


def _callable_source(value: Callable[..., Any]) -> str:
    try:
        file = inspect.getsourcefile(value) or "<unknown>"
        lines, start = inspect.getsourcelines(value)
        end = start + len(lines) - 1
        return f"{file}:{start}-{end}"
    except OSError:
        return "<unknown>"
