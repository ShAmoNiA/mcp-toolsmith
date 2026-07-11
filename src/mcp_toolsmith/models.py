from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rich.console import Console

Severity = Literal["info", "warning", "error"]
SourceKind = Literal["function", "pydantic", "mcp"]
AuditMode = Literal["static", "execute", "json", "project"]
AuditProfile = Literal["generic", "openai", "mcp"]


@dataclass(frozen=True)
class Finding:
    """One lint finding produced by the auditor."""

    rule_id: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None

    @property
    def path(self) -> str | None:
        return _split_location(self.location)[0]

    @property
    def line(self) -> int | None:
        return _split_location(self.location)[1]

    @property
    def column(self) -> int | None:
        return _split_location(self.location)[2]

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.rule_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }
        if self.location:
            payload["location"] = self.location
        if self.path:
            payload["path"] = self.path
        if self.line is not None:
            payload["line"] = self.line
        if self.column is not None:
            payload["column"] = self.column
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


@dataclass
class ToolSchema:
    """Provider-neutral representation of an LLM-callable tool."""

    name: str
    description: str
    input_schema: Any
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
    profile: AuditProfile = "generic"
    file_count: int | None = None

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
            "profile": self.profile,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "tools": [tool.as_dict() for tool in self.tools],
            "findings": [finding.as_dict() for finding in self.findings],
            "errors": self._findings_by_severity("error"),
            "warnings": self._findings_by_severity("warning"),
        }
        if self.source:
            payload["source"] = str(self.source)
        if self.mode:
            payload["mode"] = self.mode
        if self.file_count is not None:
            payload["file_count"] = self.file_count
        return payload

    def _findings_by_severity(self, severity: Severity) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for finding in self.findings:
            if finding.severity == severity:
                findings.append(finding.as_dict())
        for tool_audit in self.tools:
            for finding in tool_audit.findings:
                if finding.severity != severity:
                    continue
                payload = finding.as_dict()
                payload["tool"] = tool_audit.tool.name
                findings.append(payload)
        return findings

    def to_text(self) -> str:
        if self.mode == "project":
            return self._project_text()
        status = "[green]OK[/green]" if self.passed else "[red]FAILED[/red]"
        subject = str(self.source) if self.source else "tool catalog"
        lines = [
            f"{status} Audited {len(self.tools)} tool(s) from {subject}",
            f"Mode: {self.mode}" if self.mode else "Mode: unknown",
            f"Profile: {self.profile}",
            f"Errors: {self.error_count}  Warnings: {self.warning_count}",
        ]

        for finding in self.findings:
            lines.extend(["", _format_finding(finding)])

        for tool_audit in self.tools:
            tool = tool_audit.tool
            summary = f"{tool.name} [{tool.source_kind}] ~{tool.estimated_schema_tokens} schema tokens"
            lines.extend(["", f"[bold]{summary}[/bold]"])
            if not tool_audit.findings:
                lines.append("  [green]No findings[/green]")
                continue
            for finding in tool_audit.findings:
                lines.append("  " + _format_finding(finding))

        return "\n".join(lines)

    def _project_text(self) -> str:
        lines = [f"Audited {len(self.tools)} tools across {self.file_count or 0} files"]
        grouped: dict[str, list[tuple[str | None, Finding]]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.path or str(self.source or "project"), []).append((None, finding))
        for tool_audit in self.tools:
            for finding in tool_audit.findings:
                grouped.setdefault(finding.path or tool_audit.tool.source, []).append((tool_audit.tool.name, finding))
        for path, entries in grouped.items():
            for tool_name, finding in entries:
                location = path
                if finding.line is not None:
                    location += f":{finding.line}"
                    if finding.column is not None:
                        location += f":{finding.column}"
                lines.extend(["", location, f"  {finding.severity.upper()} {finding.rule_id}"])
                prefix = f'Tool "{tool_name}": ' if tool_name else ""
                lines.append(f"  {prefix}{finding.message}")
        lines.extend(["", f"Errors: {self.error_count}", f"Warnings: {self.warning_count}"])
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


def _split_location(location: str | None) -> tuple[str | None, int | None, int | None]:
    if not location:
        return None, None, None
    # Split from the right so Windows drive letters remain intact.
    parts = location.rsplit(":", 2)
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return parts[0], int(parts[1]), int(parts[2])
    parts = location.rsplit(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1]), None
    source_match = re.match(r"^(.+\.(?:py|json))(?::.*)?$", location, flags=re.IGNORECASE)
    if source_match:
        return source_match.group(1), None, None
    return location, None, None
