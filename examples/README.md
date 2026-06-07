# Examples

These examples are copy-pasteable inputs for `mcp-toolsmith`.

## Bad Python Tools

```bash
mcp-toolsmith audit examples/bad_tools.py --execute --all-public
```

This example intentionally uses vague function names and weak descriptions so
the audit report has something useful to catch.

## Decorated Python Tools

```bash
mcp-toolsmith audit examples/decorated_tools.py --execute
mcp-toolsmith compile examples/decorated_tools.py --execute --target mcp
```

Only functions marked with `@tool` are discovered by default.

## MCP JSON Tools

```bash
mcp-toolsmith audit examples/tools.json
mcp-toolsmith compile examples/tools.json --target openai
```

JSON tool definitions are safe by default because they do not require executing
Python source code.

