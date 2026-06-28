# Changelog

## 0.4.0

- Add provider compatibility profiles with `--profile generic`, `--profile openai`,
  and `--profile mcp`.
- Add OpenAI-style checks for names, loose schemas, deep nesting, large enums,
  array item schemas, and ignored JSON Schema keywords.
- Add MCP checks for `inputSchema` shape, required fields, missing argument
  descriptions, large schemas, and duplicate or overlapping tool names.
- Include the active audit profile in text and JSON reports.

## 0.3.0

- Add safe static auditing for `@tool`-decorated Python functions.
- Keep `--execute` as the opt-in path for runtime/Pydantic introspection.
- Add audit mode labels to text and JSON reports.
- Add `--fail-on` for CI exit-code control.

## 0.2.0

- Add `@tool` decorator for explicit trusted Python tool discovery.
- Discover only decorated Python functions by default when using `--execute`.
- Add `--all-public` to preserve broad public function and Pydantic model discovery.

## 0.1.0a1

- Add `mcp-toolsmith audit` for Python files and MCP JSON tool definitions.
- Add `mcp-toolsmith compile` for MCP and OpenAI-style tool output.
- Discover top-level Python functions and Pydantic v2 models.
- Report naming, description, schema-size, argument-description, overlap, and
  tool-poisoning findings.
- Refuse Python file execution by default; use `--execute` only for trusted
  Python files.
- Preserve user properties named like JSON Schema metadata during compilation.
