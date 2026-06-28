"""Audit and compile Python tool schemas for LLM agents."""

from mcp_toolsmith.auditor import audit_file, audit_tool, audit_tools
from mcp_toolsmith.compiler import compile_file, compile_tool, compile_tools
from mcp_toolsmith.decorators import tool
from mcp_toolsmith.introspection import UnsafePythonExecutionError
from mcp_toolsmith.models import AuditProfile, AuditReport, Finding, ToolAudit, ToolSchema

__all__ = [
    "AuditProfile",
    "AuditReport",
    "Finding",
    "ToolAudit",
    "ToolSchema",
    "UnsafePythonExecutionError",
    "audit_file",
    "audit_tool",
    "audit_tools",
    "compile_file",
    "compile_tool",
    "compile_tools",
    "tool",
]

__version__ = "0.4.0"
