from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from mcp_toolsmith.auditor import audit_file, audit_tools
from mcp_toolsmith.configuration import PerFileIgnore, matches_pattern
from mcp_toolsmith.models import AuditProfile, AuditReport, Finding, ToolSchema


def discover_files(
    target: Path,
    *,
    root: Path,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> list[Path]:
    if target.is_file():
        return [target]
    discovered: list[Path] = []
    for directory, directory_names, file_names in os.walk(target, topdown=True):
        parent = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not _is_excluded_directory(parent / name, root=root, exclude=exclude)
        )
        for name in sorted(file_names):
            path = parent / name
            if path.suffix.lower() not in {".py", ".json"}:
                continue
            relative = _relative(path, root)
            if include and not any(matches_pattern(relative, pattern) for pattern in include):
                continue
            if any(matches_pattern(relative, pattern) for pattern in exclude):
                continue
            if path.suffix.lower() == ".json" and not _is_supported_json(path):
                continue
            discovered.append(path)
    return sorted(discovered, key=lambda path: path.as_posix())


def audit_path(
    target: Path,
    *,
    root: Path,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    ignore: tuple[str, ...] = (),
    per_file_ignores: tuple[PerFileIgnore, ...] = (),
    execute: bool = False,
    all_public: bool = False,
    profile: AuditProfile = "generic",
    max_schema_depth: int = 5,
) -> AuditReport:
    if target.is_file():
        report = audit_file(
            target,
            execute=execute,
            all_public=all_public,
            profile=profile,
            max_schema_depth=max_schema_depth,
        )
        return suppress_findings(report, root=root, ignore=ignore, per_file_ignores=per_file_ignores)

    files = discover_files(target, root=root, include=include, exclude=exclude)
    tools: list[ToolSchema] = []
    load_findings: list[Finding] = []
    for path in files:
        try:
            file_report = audit_file(
                path,
                execute=execute,
                all_public=all_public,
                profile=profile,
                max_schema_depth=max_schema_depth,
            )
            tools.extend(tool_audit.tool for tool_audit in file_report.tools)
        except Exception as exc:
            load_findings.append(
                Finding(
                    rule_id="file.audit_failed",
                    severity="error",
                    message=str(exc),
                    location=str(path),
                )
            )
    report = audit_tools(tools, source=target, mode="project", profile=profile, max_schema_depth=max_schema_depth)
    report.findings = load_findings + report.findings
    report.file_count = len(files)
    return suppress_findings(report, root=root, ignore=ignore, per_file_ignores=per_file_ignores)


def suppress_findings(
    report: AuditReport,
    *,
    root: Path,
    ignore: tuple[str, ...],
    per_file_ignores: tuple[PerFileIgnore, ...],
) -> AuditReport:
    global_ignored = set(ignore)

    def keep(finding: Finding, fallback_path: str | None = None) -> bool:
        if finding.rule_id in global_ignored:
            return False
        path = finding.path or fallback_path
        if path is None:
            return True
        relative = _relative(Path(path), root)
        for entry in per_file_ignores:
            if finding.rule_id in entry.rules and matches_pattern(relative, entry.path):
                return False
        return True

    report.findings = [finding for finding in report.findings if keep(finding)]
    report.tools = [
        replace(
            tool_audit, findings=[finding for finding in tool_audit.findings if keep(finding, tool_audit.tool.source)]
        )
        for tool_audit in report.tools
    ]
    return report


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_supported_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Include unreadable/malformed JSON so the audit reports the failure.
        return True
    if isinstance(data, list):
        return bool(data) and all(isinstance(item, dict) and "name" in item for item in data)
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("tools"), list):
        return True
    return "name" in data and ("inputSchema" in data or "description" in data)


def _is_excluded_directory(path: Path, *, root: Path, exclude: tuple[str, ...]) -> bool:
    relative_placeholder = f"{_relative(path, root).rstrip('/')}/_"
    return any(matches_pattern(relative_placeholder, pattern) for pattern in exclude)
