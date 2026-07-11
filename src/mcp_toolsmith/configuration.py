from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from mcp_toolsmith.models import AuditProfile

DEFAULT_EXCLUDES = [
    "**/.git/**",
    "**/.venv/**",
    "**/venv/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
]
DEFAULT_INCLUDES = ["**/*.py", "**/*.json"]


@dataclass(frozen=True)
class PerFileIgnore:
    path: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class ToolsmithConfig:
    profile: AuditProfile = "generic"
    fail_on: str = "error"
    include: tuple[str, ...] = tuple(DEFAULT_INCLUDES)
    exclude: tuple[str, ...] = tuple(DEFAULT_EXCLUDES)
    ignore: tuple[str, ...] = ()
    per_file_ignores: tuple[PerFileIgnore, ...] = ()
    max_schema_depth: int = 5
    source: Path | None = None
    root: Path = field(default_factory=Path.cwd)


def find_pyproject(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> ToolsmithConfig:
    pyproject = find_pyproject(start)
    if pyproject is None:
        return ToolsmithConfig(root=(start or Path.cwd()).resolve())

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    raw = data.get("tool", {}).get("mcp-toolsmith", {})
    if not isinstance(raw, dict):
        raise ValueError("[tool.mcp-toolsmith] must be a TOML table")

    profile = raw.get("profile", "generic")
    fail_on = raw.get("fail-on", "error")
    include = _string_list(raw, "include", DEFAULT_INCLUDES)
    configured_excludes = _string_list(raw, "exclude", [])
    exclude = [*DEFAULT_EXCLUDES, *configured_excludes]
    ignore = _string_list(raw, "ignore", [])
    max_depth = raw.get("max-schema-depth", 5)
    if profile not in {"generic", "openai", "mcp"}:
        raise ValueError("profile must be one of: generic, openai, mcp")
    if fail_on not in {"error", "warning", "never"}:
        raise ValueError("fail-on must be one of: error, warning, never")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 1:
        raise ValueError("max-schema-depth must be a positive integer")

    per_file: list[PerFileIgnore] = []
    raw_per_file = raw.get("per-file-ignores", [])
    if not isinstance(raw_per_file, list):
        raise ValueError("per-file-ignores must be an array of tables")
    for entry in raw_per_file:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("each per-file-ignores entry requires a string path")
        rules = entry.get("rules", [])
        if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
            raise ValueError("per-file-ignores rules must be a list of strings")
        per_file.append(PerFileIgnore(entry["path"], tuple(rules)))

    return ToolsmithConfig(
        profile=profile,
        fail_on=fail_on,
        include=tuple(include),
        exclude=tuple(exclude),
        ignore=tuple(ignore),
        per_file_ignores=tuple(per_file),
        max_schema_depth=max_depth,
        source=pyproject,
        root=pyproject.parent,
    )


def matches_pattern(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    normalized_pattern = pattern.replace("\\", "/").lstrip("./")
    if fnmatch.fnmatchcase(normalized, normalized_pattern):
        return True
    if normalized_pattern.startswith("**/"):
        if fnmatch.fnmatchcase(normalized, normalized_pattern[3:]):
            return True
    if "/**/" in normalized_pattern:
        if fnmatch.fnmatchcase(normalized, normalized_pattern.replace("/**/", "/")):
            return True
    return False


def _string_list(raw: dict[str, Any], key: str, default: list[str]) -> list[str]:
    value = raw.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return value
