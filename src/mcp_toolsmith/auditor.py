from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator
from pydantic import BaseModel

from mcp_toolsmith.introspection import (
    function_to_tool_schema,
    load_tool_schemas,
    pydantic_model_to_tool_schema,
)
from mcp_toolsmith.models import AuditMode, AuditProfile, AuditReport, Finding, ToolAudit, ToolSchema
from mcp_toolsmith.static_introspection import load_static_tool_schemas

_GOOD_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")
_OPENAI_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VAGUE_NAMES = {
    "action",
    "call",
    "do",
    "execute",
    "handle",
    "invoke",
    "manage",
    "operation",
    "perform",
    "process",
    "run",
    "tool",
    "use",
}
_GENERIC_PROPERTY_NAMES = {
    "args",
    "argument",
    "arguments",
    "data",
    "input",
    "inputs",
    "object",
    "options",
    "params",
    "payload",
    "request",
}
_OPENAI_IGNORED_SCHEMA_KEYWORDS = {
    "$defs",
    "$id",
    "$schema",
    "allOf",
    "anyOf",
    "contains",
    "definitions",
    "dependentRequired",
    "dependentSchemas",
    "else",
    "examples",
    "if",
    "not",
    "oneOf",
    "patternProperties",
    "propertyNames",
    "then",
    "unevaluatedProperties",
    "unevaluatedItems",
}
_POISON_PATTERNS = {
    "ignore previous": "Tool descriptions should not override chat or system instructions.",
    "ignore all previous": "Tool descriptions should not override chat or system instructions.",
    "system prompt": "Tool metadata should not ask the model to reveal or modify prompts.",
    "developer message": "Tool metadata should not mention higher-priority messages.",
    "always call": "Tool metadata should describe capability, not force tool selection.",
    "must call": "Tool metadata should describe capability, not force tool selection.",
    "never call": "Tool metadata should describe capability, not force tool selection.",
}


def audit_file(
    path: str | Path,
    *,
    execute: bool = False,
    all_public: bool = False,
    profile: AuditProfile = "generic",
    max_schema_depth: int = 5,
) -> AuditReport:
    """Audit all tools discovered in a Python or MCP JSON file."""

    source = Path(path)
    mode: AuditMode = "json"
    if source.suffix.lower() == ".py":
        mode = "execute" if execute else "static"
    if source.suffix.lower() == ".json":
        tools = _load_json_tool_schemas_for_audit(source)
    elif source.suffix.lower() == ".py" and not execute:
        tools = load_static_tool_schemas(source)
    else:
        tools = load_tool_schemas(source, execute_python=execute, all_public=all_public)
    return audit_tools(
        tools,
        source=source,
        mode=mode,
        profile=profile,
        max_schema_depth=max_schema_depth,
    )


def audit_tool(
    tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any],
    *,
    profile: AuditProfile = "generic",
    max_schema_depth: int = 5,
) -> ToolAudit:
    """Audit one tool-like object.

    Accepted inputs are `ToolSchema`, Python functions, Pydantic v2 models, and
    MCP-style dictionaries with `name` and `inputSchema`.
    """

    schema = _coerce_tool_schema(tool)
    return ToolAudit(tool=schema, findings=_audit_one(schema, profile=profile, max_schema_depth=max_schema_depth))


def audit_tools(
    tools: list[ToolSchema],
    source: Path | None = None,
    mode: AuditMode | None = None,
    *,
    profile: AuditProfile = "generic",
    max_schema_depth: int = 5,
) -> AuditReport:
    """Audit a catalog of provider-neutral tool schemas."""

    _validate_profile(profile)
    tool_audits = [audit_tool(tool, profile=profile, max_schema_depth=max_schema_depth) for tool in tools]
    findings = _audit_catalog(tools)
    findings.extend(_audit_catalog_for_profile(tools, profile))
    if not tools:
        findings.append(
            Finding(
                rule_id="catalog.no_tools",
                severity="warning",
                message=(
                    "No @tool-decorated functions were discovered." if mode == "static" else "No tools were discovered."
                ),
                suggestion=(
                    "Add @tool or use --execute --all-public for trusted files."
                    if mode == "static"
                    else "Add MCP JSON definitions, decorate trusted Python functions with @tool, or use --all-public."
                ),
            )
        )
    return AuditReport(tools=tool_audits, findings=findings, source=source, mode=mode, profile=profile)


def _coerce_tool_schema(tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any]) -> ToolSchema:
    if isinstance(tool, ToolSchema):
        return tool
    if isinstance(tool, dict):
        return _mcp_definition_to_tool_schema_for_audit(tool)
    if inspect.isclass(tool) and issubclass(tool, BaseModel):
        return pydantic_model_to_tool_schema(tool)
    if callable(tool):
        return function_to_tool_schema(tool)
    raise TypeError("tool must be a ToolSchema, function, Pydantic model, or MCP definition dict")


def _validate_profile(profile: AuditProfile) -> None:
    if profile not in {"generic", "openai", "mcp"}:
        raise ValueError("profile must be one of: generic, openai, mcp")


def _load_json_tool_schemas_for_audit(path: Path) -> list[ToolSchema]:
    data = json.loads(path.read_text(encoding="utf-8"))
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
    return [
        _mcp_definition_to_tool_schema_for_audit(definition, source=str(path))
        for index, definition in enumerate(definitions)
    ]


def _mcp_definition_to_tool_schema_for_audit(definition: dict[str, Any], source: str = "<memory>") -> ToolSchema:
    metadata: dict[str, Any] = {"definition": definition}
    if "inputSchema" not in definition:
        metadata["mcp_input_schema_missing"] = True

    return ToolSchema(
        name=str(definition.get("name", "")),
        description=str(definition.get("description", "")),
        input_schema=definition.get("inputSchema"),
        source=source,
        source_kind="mcp",
        metadata=metadata,
    )


def _audit_one(tool: ToolSchema, *, profile: AuditProfile, max_schema_depth: int) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_audit_name(tool))
    findings.extend(_audit_description(tool))
    findings.extend(_audit_schema(tool))
    findings.extend(_audit_python_metadata(tool))
    findings.extend(_audit_tool_for_profile(tool, profile, max_schema_depth))
    return findings


def _audit_name(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    name = tool.name.strip()
    if not name:
        findings.append(
            Finding(
                rule_id="name.missing",
                severity="error",
                message="Tool name is empty.",
                location=tool.source,
                suggestion="Use a short verb_noun name such as search_docs or create_ticket.",
            )
        )
        return findings

    if not _GOOD_NAME_RE.match(name):
        findings.append(
            Finding(
                rule_id="name.format",
                severity="warning",
                message="Tool name may be rejected or misread by providers.",
                location=tool.source,
                suggestion="Use 2-64 letters, numbers, underscores, or hyphens, starting with a letter.",
            )
        )

    normalized = name.lower().replace("-", "_")
    if normalized in _VAGUE_NAMES:
        findings.append(
            Finding(
                rule_id="name.vague",
                severity="warning",
                message="Tool name is too generic for reliable tool selection.",
                location=tool.source,
                suggestion="Use a specific verb_noun name, for example search_docs or fetch_invoice.",
            )
        )
    return findings


def _audit_description(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    description = tool.description.strip()
    if not description:
        findings.append(
            Finding(
                rule_id="description.missing",
                severity="error",
                message="Tool description is missing.",
                location=tool.source,
                suggestion="Describe when the agent should call this tool in one concrete sentence.",
            )
        )
        return findings

    if len(description.split()) < 5:
        findings.append(
            Finding(
                rule_id="description.too_short",
                severity="warning",
                message="Tool description is too short to guide model selection.",
                location=tool.source,
                suggestion="Mention the task, useful inputs, and expected result.",
            )
        )

    lower_description = description.lower()
    for pattern, suggestion in _POISON_PATTERNS.items():
        if pattern in lower_description:
            findings.append(
                Finding(
                    rule_id="security.tool_poisoning",
                    severity="error",
                    message=f"Tool description contains suspicious instruction-like text: {pattern!r}.",
                    location=tool.source,
                    suggestion=suggestion,
                )
            )
    return findings


def _audit_schema(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    schema = tool.input_schema
    if not isinstance(schema, dict):
        return [
            Finding(
                rule_id="schema.not_object",
                severity="error",
                message="Tool input schema must be a JSON object.",
                location=tool.source,
            )
        ]

    schema_type = schema.get("type")
    if schema_type not in {None, "object"}:
        findings.append(
            Finding(
                rule_id="schema.type",
                severity="error",
                message="Tool input schema should be an object schema.",
                location=tool.source,
                suggestion='Use a top-level {"type": "object", "properties": {...}} schema.',
            )
        )

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        findings.append(
            Finding(
                rule_id="schema.invalid_json_schema",
                severity="error",
                message=f"Input schema is not valid JSON Schema: {exc.message}",
                location=tool.source,
                suggestion="Fix the schema before compiling it for a provider.",
            )
        )

    properties = schema.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        findings.append(
            Finding(
                rule_id="schema.properties",
                severity="error",
                message="Schema properties must be an object.",
                location=tool.source,
            )
        )
        return findings

    missing_descriptions = [
        name
        for name, property_schema in properties.items()
        if isinstance(property_schema, dict) and not str(property_schema.get("description", "")).strip()
    ]
    if missing_descriptions:
        preview = ", ".join(missing_descriptions[:5])
        overflow = "" if len(missing_descriptions) <= 5 else f", +{len(missing_descriptions) - 5} more"
        findings.append(
            Finding(
                rule_id="schema.arg_description_missing",
                severity="warning",
                message=f"Argument descriptions are missing for: {preview}{overflow}.",
                location=tool.source,
                suggestion="Add Pydantic Field(description=...) or docstring Args entries.",
            )
        )

    required = schema.get("required", [])
    if isinstance(required, list) and len(required) >= 8:
        findings.append(
            Finding(
                rule_id="schema.too_many_required",
                severity="warning",
                message=f"Schema has {len(required)} required arguments.",
                location=tool.source,
                suggestion="Consider grouping related inputs into a smaller object or splitting the tool.",
            )
        )

    token_count = tool.estimated_schema_tokens
    if token_count > 2500:
        severity = "error"
    elif token_count > 1000:
        severity = "warning"
    else:
        severity = None
    if severity:
        findings.append(
            Finding(
                rule_id="schema.large",
                severity=severity,
                message=f"Schema is large at roughly {token_count} tokens.",
                location=tool.source,
                suggestion="Remove redundant titles/examples or compile with a future compact profile.",
            )
        )

    enum_findings = _audit_large_enums(schema, tool.source)
    findings.extend(enum_findings)
    findings.extend(_audit_schema_descriptions_for_poisoning(schema, tool.source))
    return findings


def _audit_python_metadata(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    for parameter_name in tool.metadata.get("static_variadic_parameters", []):
        findings.append(
            Finding(
                rule_id="python.variadic_parameter",
                severity="error",
                message=f"Variadic parameter {parameter_name!r} cannot be represented reliably.",
                location=tool.source,
                suggestion="Replace *args/**kwargs with explicit typed parameters.",
            )
        )
    for parameter_name in tool.metadata.get("static_missing_annotations", []):
        findings.append(
            Finding(
                rule_id="python.annotation_missing",
                severity="warning",
                message=f"Parameter {parameter_name!r} is missing a type annotation.",
                location=tool.source,
                suggestion="Add a Python type annotation so the JSON Schema is specific.",
            )
        )
    for parameter_name in tool.metadata.get("static_unknown_annotations", []):
        findings.append(
            Finding(
                rule_id="python.static_annotation_unknown",
                severity="warning",
                message=f"Parameter {parameter_name!r} has a type annotation static audit cannot map yet.",
                location=tool.source,
                suggestion="Use str, int, float, bool, list[T], or dict for static audit, or use --execute.",
            )
        )

    function = tool.metadata.get("callable")
    if not function:
        return findings

    signature = inspect.signature(function)
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            findings.append(
                Finding(
                    rule_id="python.variadic_parameter",
                    severity="error",
                    message=f"Variadic parameter {parameter.name!r} cannot be represented reliably.",
                    location=tool.source,
                    suggestion="Replace *args/**kwargs with explicit typed parameters.",
                )
            )
        if parameter.annotation is inspect.Signature.empty:
            findings.append(
                Finding(
                    rule_id="python.annotation_missing",
                    severity="warning",
                    message=f"Parameter {parameter.name!r} is missing a type annotation.",
                    location=tool.source,
                    suggestion="Add a Python type annotation so the JSON Schema is specific.",
                )
            )
    return findings


def _audit_tool_for_profile(tool: ToolSchema, profile: AuditProfile, max_schema_depth: int) -> list[Finding]:
    if profile == "generic":
        return []
    if profile == "openai":
        return _audit_openai_tool(tool, max_schema_depth)
    if profile == "mcp":
        return _audit_mcp_tool(tool)
    return []


def _audit_openai_tool(tool: ToolSchema, max_schema_depth: int = 5) -> list[Finding]:
    findings: list[Finding] = []
    name = tool.name.strip()
    if not name:
        findings.append(
            Finding(
                rule_id="openai.name.missing",
                severity="error",
                message="Tool name is empty.",
                location=tool.source,
                suggestion="Use a specific function name such as search_documents.",
            )
        )
    elif len(name) > 64:
        findings.append(
            Finding(
                rule_id="openai.name.too_long",
                severity="error",
                message=(
                    f"Tool name {name!r} is {len(name)} characters; OpenAI-style names must be 64 characters or fewer."
                ),
                location=tool.source,
                suggestion="Shorten the tool name while keeping a clear verb_noun shape.",
            )
        )
    elif not _OPENAI_NAME_RE.match(name):
        findings.append(
            Finding(
                rule_id="openai.name.invalid",
                severity="error",
                message=f"Tool name {name!r} contains invalid characters for OpenAI-style tool calling.",
                location=tool.source,
                suggestion="Use only letters, numbers, underscores, and hyphens.",
            )
        )

    if name.lower().replace("-", "_") in _VAGUE_NAMES:
        findings.append(
            Finding(
                rule_id="openai.name.vague",
                severity="warning",
                message="Tool name is too generic for OpenAI-style tool calling.",
                location=tool.source,
                suggestion="Rename it to describe the concrete action, such as search_documents.",
            )
        )

    if len(tool.description.strip().split()) < 5:
        findings.append(
            Finding(
                rule_id="openai.description.too_short",
                severity="warning",
                message="Tool description is too short for reliable OpenAI-style tool selection.",
                location=tool.source,
                suggestion="Describe when to use the tool and what result it returns.",
            )
        )

    schema = tool.input_schema
    if not isinstance(schema, dict):
        findings.append(
            Finding(
                rule_id="openai.schema.not_object",
                severity="error",
                message="Tool parameters must be a JSON object schema for OpenAI-style tool calling.",
                location=tool.source,
            )
        )
        return findings

    if schema.get("type") not in {None, "object"}:
        findings.append(
            Finding(
                rule_id="openai.schema.not_object",
                severity="error",
                message="OpenAI-style tool parameters should use a top-level object schema.",
                location=tool.source,
                suggestion='Use {"type": "object", "properties": {...}}.',
            )
        )

    findings.extend(_audit_required_properties_exist(schema, tool.source, "openai.schema.required_unknown"))
    findings.extend(
        _audit_property_descriptions(
            schema,
            tool.source,
            "openai.schema.arg_description_missing",
            "OpenAI-style tool arguments should include descriptions.",
        )
    )
    findings.extend(_audit_openai_generic_properties(schema, tool.source))

    nesting_depth = _schema_nesting_depth(schema)
    if nesting_depth > max_schema_depth:
        findings.append(
            Finding(
                rule_id="openai.schema.too_deep",
                severity="warning",
                message=(
                    f"Tool {tool.name!r} has a deeply nested schema. "
                    "OpenAI tool calling may perform worse with deeply nested parameters."
                ),
                location=tool.source,
                suggestion="Prefer flatter parameters or split the tool into narrower operations.",
            )
        )

    findings.extend(_audit_profile_large_enums(schema, tool.source, "openai.schema.large_enum"))
    findings.extend(_audit_array_items(schema, tool.source))
    findings.extend(_audit_additional_properties(schema, tool.source))
    findings.extend(_audit_openai_ignored_keywords(schema, tool.source))
    return findings


def _audit_mcp_tool(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    name = tool.name.strip()
    if not name:
        findings.append(
            Finding(
                rule_id="mcp.name.missing",
                severity="error",
                message="MCP tools should include a name.",
                location=tool.source,
            )
        )
    elif name.lower().replace("-", "_") in _VAGUE_NAMES:
        findings.append(
            Finding(
                rule_id="mcp.name.vague",
                severity="warning",
                message="MCP tool name is too vague for reliable client display and tool selection.",
                location=tool.source,
                suggestion="Use a specific verb_noun name such as refresh_consent.",
            )
        )

    if not tool.description.strip():
        findings.append(
            Finding(
                rule_id="mcp.description.missing",
                severity="error",
                message="MCP tools should include a description.",
                location=tool.source,
                suggestion="Describe what the tool does in one concrete sentence.",
            )
        )

    schema = tool.input_schema
    if tool.metadata.get("mcp_input_schema_missing"):
        findings.append(
            Finding(
                rule_id="mcp.input_schema.missing",
                severity="error",
                message="MCP tool definition is missing inputSchema.",
                location=tool.source,
                suggestion='Add an inputSchema object, even if it is {"type": "object", "properties": {}}.',
            )
        )
        return findings

    if not isinstance(schema, dict):
        findings.append(
            Finding(
                rule_id="mcp.input_schema.not_object",
                severity="error",
                message="MCP inputSchema must be a JSON object.",
                location=tool.source,
            )
        )
        return findings

    if schema.get("type") not in {None, "object"}:
        findings.append(
            Finding(
                rule_id="mcp.input_schema.not_object",
                severity="error",
                message="MCP inputSchema should describe an object.",
                location=tool.source,
                suggestion='Use {"type": "object", "properties": {...}}.',
            )
        )

    findings.extend(_audit_required_properties_exist(schema, tool.source, "mcp.input_schema.required_unknown"))
    findings.extend(
        _audit_property_descriptions(
            schema,
            tool.source,
            "mcp.input_schema.arg_description_missing",
            "MCP input fields should include descriptions.",
        )
    )

    token_count = tool.estimated_schema_tokens
    if token_count > 2500:
        severity = "error"
    elif token_count > 1000:
        severity = "warning"
    else:
        severity = None
    if severity:
        findings.append(
            Finding(
                rule_id="mcp.input_schema.large",
                severity=severity,
                message=f"MCP inputSchema is large at roughly {token_count} tokens.",
                location=tool.source,
                suggestion="Trim redundant schema metadata or split very broad tools.",
            )
        )
    return findings


def _audit_catalog(tools: list[ToolSchema]) -> list[Finding]:
    findings: list[Finding] = []
    for left_index, left in enumerate(tools):
        for right in tools[left_index + 1 :]:
            if _looks_overlapping(left, right):
                findings.append(
                    Finding(
                        rule_id="catalog.overlap",
                        severity="warning",
                        message=f"Tools {left.name!r} and {right.name!r} look semantically overlapping.",
                        location=left.source,
                        suggestion="Merge them, rename one more specifically, or clarify their descriptions.",
                    )
                )
    return findings


def _audit_catalog_for_profile(tools: list[ToolSchema], profile: AuditProfile) -> list[Finding]:
    if profile != "mcp":
        return []

    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for tool in tools:
        normalized = tool.name.strip().lower()
        if not normalized:
            continue
        if normalized in seen:
            findings.append(
                Finding(
                    rule_id="mcp.catalog.duplicate_name",
                    severity="error",
                    message=f"MCP tool name {tool.name!r} is duplicated.",
                    location=tool.source,
                    suggestion="MCP tool names should be unique within a server.",
                )
            )
        else:
            seen[normalized] = tool.source

    for left_index, left in enumerate(tools):
        for right in tools[left_index + 1 :]:
            if _looks_overlapping(left, right):
                findings.append(
                    Finding(
                        rule_id="mcp.catalog.overlap",
                        severity="warning",
                        message=f"MCP tools {left.name!r} and {right.name!r} look semantically overlapping.",
                        location=left.source,
                        suggestion="Rename or clarify descriptions so clients and models can distinguish them.",
                    )
                )
    return findings


def _looks_overlapping(left: ToolSchema, right: ToolSchema) -> bool:
    left_name = _tokenize(left.name)
    right_name = _tokenize(right.name)
    if left_name and right_name and _jaccard(left_name, right_name) >= 0.75:
        return True

    left_description = _tokenize(left.description)
    right_description = _tokenize(right.description)
    return bool(left_description and right_description and _jaccard(left_description, right_description) >= 0.8)


def _audit_required_properties_exist(schema: dict[str, Any], source: str, rule_id: str) -> list[Finding]:
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, dict):
        return []

    missing = sorted(str(name) for name in set(required) - set(properties))
    if not missing:
        return []
    preview = ", ".join(missing[:5])
    overflow = "" if len(missing) <= 5 else f", +{len(missing) - 5} more"
    return [
        Finding(
            rule_id=rule_id,
            severity="error",
            message=f"Required fields are missing from properties: {preview}{overflow}.",
            location=source,
            suggestion="Define every required field in schema properties or remove it from required.",
        )
    ]


def _audit_property_descriptions(
    schema: dict[str, Any],
    source: str,
    rule_id: str,
    suggestion: str,
) -> list[Finding]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []

    missing_descriptions = [
        name
        for name, property_schema in properties.items()
        if isinstance(property_schema, dict) and not str(property_schema.get("description", "")).strip()
    ]
    if not missing_descriptions:
        return []

    preview = ", ".join(missing_descriptions[:5])
    overflow = "" if len(missing_descriptions) <= 5 else f", +{len(missing_descriptions) - 5} more"
    return [
        Finding(
            rule_id=rule_id,
            severity="warning",
            message=f"Tool has input fields without descriptions: {preview}{overflow}.",
            location=source,
            suggestion=suggestion,
        )
    ]


def _audit_openai_generic_properties(schema: dict[str, Any], source: str) -> list[Finding]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []

    generic_properties: list[str] = []
    loose_objects: list[str] = []
    for name, property_schema in properties.items():
        normalized = str(name).lower().replace("-", "_")
        if normalized in _GENERIC_PROPERTY_NAMES:
            generic_properties.append(str(name))
        if isinstance(property_schema, dict) and property_schema.get("type") == "object":
            child_properties = property_schema.get("properties")
            if not isinstance(child_properties, dict) or not child_properties:
                loose_objects.append(str(name))

    names = sorted(set(generic_properties + loose_objects))
    if not names:
        return []
    preview = ", ".join(names[:5])
    overflow = "" if len(names) <= 5 else f", +{len(names) - 5} more"
    return [
        Finding(
            rule_id="openai.schema.property_too_generic",
            severity="warning",
            message=f"Object properties are too generic or loosely defined: {preview}{overflow}.",
            location=source,
            suggestion="Use descriptive argument names and define nested object properties explicitly.",
        )
    ]


def _schema_nesting_depth(node: Any) -> int:
    if isinstance(node, dict):
        if not node:
            return 1
        return 1 + max((_schema_nesting_depth(value) for value in node.values()), default=0)
    if isinstance(node, list):
        if not node:
            return 1
        return 1 + max((_schema_nesting_depth(value) for value in node), default=0)
    return 0


def _audit_profile_large_enums(schema: dict[str, Any], source: str, rule_id: str) -> list[Finding]:
    findings: list[Finding] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            enum_values = node.get("enum")
            if isinstance(enum_values, list) and len(enum_values) > 20:
                findings.append(
                    Finding(
                        rule_id=rule_id,
                        severity="warning",
                        message=f"Enum at {path} has {len(enum_values)} values.",
                        location=source,
                        suggestion="Prefer a smaller enum or validate open-ended values inside the tool.",
                    )
                )
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings


def _audit_array_items(schema: dict[str, Any], source: str) -> list[Finding]:
    findings: list[Finding] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "array":
                items = node.get("items")
                if not isinstance(items, dict) or not _schema_has_type_hint(items):
                    findings.append(
                        Finding(
                            rule_id="openai.schema.array_items_missing",
                            severity="warning",
                            message=f"Array schema at {path} does not define a clear item type.",
                            location=source,
                            suggestion='Add an items schema such as {"type": "string"}.',
                        )
                    )
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings


def _schema_has_type_hint(schema: dict[str, Any]) -> bool:
    return any(key in schema for key in ("type", "enum", "const", "oneOf", "anyOf", "allOf", "$ref"))


def _audit_additional_properties(schema: dict[str, Any], source: str) -> list[Finding]:
    findings: list[Finding] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                additional_properties = node.get("additionalProperties")
                properties = node.get("properties")
                if additional_properties is True or isinstance(additional_properties, dict):
                    findings.append(
                        Finding(
                            rule_id="openai.schema.additional_properties_loose",
                            severity="warning",
                            message=f"Object schema at {path} allows loose additionalProperties.",
                            location=source,
                            suggestion=(
                                "Define explicit properties and set additionalProperties to false when possible."
                            ),
                        )
                    )
                elif additional_properties is None and not isinstance(properties, dict):
                    findings.append(
                        Finding(
                            rule_id="openai.schema.additional_properties_loose",
                            severity="warning",
                            message=f"Object schema at {path} has no explicit properties.",
                            location=source,
                            suggestion="Define object properties explicitly so the model knows what to provide.",
                        )
                    )
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings


def _audit_openai_ignored_keywords(schema: dict[str, Any], source: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _OPENAI_IGNORED_SCHEMA_KEYWORDS and (key, path) not in seen:
                    seen.add((key, path))
                    findings.append(
                        Finding(
                            rule_id="openai.schema.keyword_ignored",
                            severity="warning",
                            message=(
                                f"JSON Schema keyword {key!r} at {path} may be ignored or unsupported "
                                "by OpenAI-style tool calling."
                            ),
                            location=source,
                            suggestion=(
                                "Keep tool schemas close to simple object, array, scalar, enum, "
                                "and required constraints."
                            ),
                        )
                    )
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings


def _tokenize(text: str) -> set[str]:
    stopwords = {"a", "an", "and", "for", "from", "in", "of", "or", "the", "to", "with"}
    return {token for token in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(token) > 2 and token not in stopwords}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right)


def _audit_large_enums(schema: dict[str, Any], source: str) -> list[Finding]:
    findings: list[Finding] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            enum_values = node.get("enum")
            if isinstance(enum_values, list) and len(enum_values) > 20:
                findings.append(
                    Finding(
                        rule_id="schema.large_enum",
                        severity="warning",
                        message=f"Enum at {path} has {len(enum_values)} values.",
                        location=source,
                        suggestion="Use a narrower enum or let the tool validate values at runtime.",
                    )
                )
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings


def _audit_schema_descriptions_for_poisoning(schema: dict[str, Any], source: str) -> list[Finding]:
    findings: list[Finding] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            description = node.get("description")
            if isinstance(description, str):
                lower_description = description.lower()
                for pattern, suggestion in _POISON_PATTERNS.items():
                    if pattern in lower_description:
                        findings.append(
                            Finding(
                                rule_id="security.schema_poisoning",
                                severity="error",
                                message=f"Schema description at {path} contains suspicious text: {pattern!r}.",
                                location=source,
                                suggestion=suggestion,
                            )
                        )
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(schema, "$")
    return findings
