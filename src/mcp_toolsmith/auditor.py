from __future__ import annotations

import inspect
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
    mcp_definition_to_tool_schema,
    pydantic_model_to_tool_schema,
)
from mcp_toolsmith.models import AuditMode, AuditReport, Finding, ToolAudit, ToolSchema
from mcp_toolsmith.static_introspection import load_static_tool_schemas

_GOOD_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")
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
) -> AuditReport:
    """Audit all tools discovered in a Python or MCP JSON file."""

    source = Path(path)
    mode = "json"
    if source.suffix.lower() == ".py":
        mode = "execute" if execute else "static"
    if source.suffix.lower() == ".py" and not execute:
        tools = load_static_tool_schemas(source)
    else:
        tools = load_tool_schemas(source, execute_python=execute, all_public=all_public)
    return audit_tools(
        tools,
        source=source,
        mode=mode,
    )


def audit_tool(tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any]) -> ToolAudit:
    """Audit one tool-like object.

    Accepted inputs are `ToolSchema`, Python functions, Pydantic v2 models, and
    MCP-style dictionaries with `name` and `inputSchema`.
    """

    schema = _coerce_tool_schema(tool)
    return ToolAudit(tool=schema, findings=_audit_one(schema))


def audit_tools(tools: list[ToolSchema], source: Path | None = None, mode: AuditMode | None = None) -> AuditReport:
    """Audit a catalog of provider-neutral tool schemas."""

    tool_audits = [audit_tool(tool) for tool in tools]
    findings = _audit_catalog(tools)
    if not tools:
        findings.append(
            Finding(
                rule_id="catalog.no_tools",
                severity="warning",
                message=(
                    "No @tool-decorated functions were discovered."
                    if mode == "static"
                    else "No tools were discovered."
                ),
                suggestion=(
                    "Add @tool or use --execute --all-public for trusted files."
                    if mode == "static"
                    else "Add MCP JSON definitions, decorate trusted Python functions with @tool, or use --all-public."
                ),
            )
        )
    return AuditReport(tools=tool_audits, findings=findings, source=source, mode=mode)


def _coerce_tool_schema(tool: ToolSchema | Callable[..., Any] | type[BaseModel] | dict[str, Any]) -> ToolSchema:
    if isinstance(tool, ToolSchema):
        return tool
    if isinstance(tool, dict):
        return mcp_definition_to_tool_schema(tool)
    if inspect.isclass(tool) and issubclass(tool, BaseModel):
        return pydantic_model_to_tool_schema(tool)
    if callable(tool):
        return function_to_tool_schema(tool)
    raise TypeError("tool must be a ToolSchema, function, Pydantic model, or MCP definition dict")


def _audit_one(tool: ToolSchema) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_audit_name(tool))
    findings.extend(_audit_description(tool))
    findings.extend(_audit_schema(tool))
    findings.extend(_audit_python_metadata(tool))
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
                        suggestion="Merge them, rename one more specifically, or clarify their descriptions.",
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


def _tokenize(text: str) -> set[str]:
    stopwords = {"a", "an", "and", "for", "from", "in", "of", "or", "the", "to", "with"}
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9]+", text.lower())
        if len(token) > 2 and token not in stopwords
    }


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
