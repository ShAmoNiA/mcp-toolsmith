from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rich.console import Console

Severity = Literal["info", "warning", "error"]
SourceKind = Literal["function", "pydantic", "mcp"]
AuditMode = Literal["static", "execute", "json"]


@dataclass(frozen=True)
class Finding:
    """One lint finding produced by the auditor."""

    rule_id: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }
        if self.location:
            payload["location"] = self.location
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


@dataclass
class ToolSchema:
    """Provider-neutral representation of an LLM-callable tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    source: str
    source_kind: SourceKind
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)

    def schema_json(self) -> str:
        return json.dumps(self.input_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def estimated_schema_tokens(self) -> int:
        # A rough but useful planning estimate for GPT-style tokenizers.
        return max(1, len(self.schema_json()) // 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "source": self.source,
            "source_kind": self.source_kind,
            "estimated_schema_tokens": self.estimated_schema_tokens,
        }


@dataclass
class ToolAudit:
    """Audit result for one tool."""

    tool: ToolSchema
    findings: list[Finding] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(finding.severity == "error" for finding in self.findings)

    @property
    def warning_count(self) -> int:
        return sum(finding.severity == "warning" for finding in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool.as_dict(),
            "findings": [finding.as_dict() for finding in self.findings],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


@dataclass
class AuditReport:
    """Complete audit report for a tool catalog."""

    tools: list[ToolAudit]
    findings: list[Finding] = field(default_factory=list)
    source: Path | None = None
    mode: AuditMode | None = None

    @property
    def error_count(self) -> int:
        tool_errors = sum(tool.error_count for tool in self.tools)
        report_errors = sum(finding.severity == "error" for finding in self.findings)
        return tool_errors + report_errors

    @property
    def warning_count(self) -> int:
        tool_warnings = sum(tool.warning_count for tool in self.tools)
        report_warnings = sum(finding.severity == "warning" for finding in self.findings)
        return tool_warnings + report_warnings

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "tools": [tool.as_dict() for tool in self.tools],
            "findings": [finding.as_dict() for finding in self.findings],
        }
        if self.source:
            payload["source"] = str(self.source)
        if self.mode:
            payload["mode"] = self.mode
        return payload

    def to_text(self) -> str:
        status = "[green]OK[/green]" if self.passed else "[red]FAILED[/red]"
        subject = str(self.source) if self.source else "tool catalog"
        lines = [
            f"{status} Audited {len(self.tools)} tool(s) from {subject}",
            f"Mode: {self.mode}" if self.mode else "Mode: unknown",
            f"Errors: {self.error_count}  Warnings: {self.warning_count}",
        ]

        for finding in self.findings:
            lines.extend(["", _format_finding(finding)])

        for tool_audit in self.tools:
            tool = tool_audit.tool
            summary = (
                f"{tool.name} [{tool.source_kind}] "
                f"~{tool.estimated_schema_tokens} schema tokens"
            )
            lines.extend(["", f"[bold]{summary}[/bold]"])
            if not tool_audit.findings:
                lines.append("  [green]No findings[/green]")
                continue
            for finding in tool_audit.findings:
                lines.append("  " + _format_finding(finding))

        return "\n".join(lines)

    def print(self, console: Console | None = None) -> None:
        (console or Console()).print(self)

    def __rich_console__(self, console: Console, options: Any) -> Any:
        yield self.to_text()

    def __str__(self) -> str:
        return self.to_text()


def _format_finding(finding: Finding) -> str:
    color = {"error": "red", "warning": "yellow", "info": "cyan"}[finding.severity]
    location = f" ({finding.location})" if finding.location else ""
    message = f"[{color}]{finding.severity.upper()}[/{color}] {finding.rule_id}{location}: {finding.message}"
    if finding.suggestion:
        message += f" Suggestion: {finding.suggestion}"
    return message
