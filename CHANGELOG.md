# Changelog

## 0.1.0a1

- Add `mcp-toolsmith audit` for Python files and MCP JSON tool definitions.
- Add `mcp-toolsmith compile` for MCP and OpenAI-style tool output.
- Discover top-level Python functions and Pydantic v2 models.
- Report naming, description, schema-size, argument-description, overlap, and
  tool-poisoning findings.
- Refuse Python file execution by default; use `--execute` only for trusted
  Python files.
- Preserve user properties named like JSON Schema metadata during compilation.
