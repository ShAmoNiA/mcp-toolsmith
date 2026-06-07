# mcp-toolsmith

[![PyPI version](https://img.shields.io/pypi/v/mcp-toolsmith.svg)](https://pypi.org/project/mcp-toolsmith/)
[![Python versions](https://img.shields.io/pypi/pyversions/mcp-toolsmith.svg)](https://pypi.org/project/mcp-toolsmith/)
[![CI](https://github.com/ShAmoNiA/mcp-toolsmith/actions/workflows/ci.yml/badge.svg)](https://github.com/ShAmoNiA/mcp-toolsmith/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`mcp-toolsmith` audits and compiles Python tool schemas for LLM agents, catching
vague names, missing argument descriptions, oversized schemas, overlapping
tools, and prompt-injection-like metadata before your agent uses them.

**Pre-1.0:** JSON tool files are safe by default. Python files require
`--execute` and should only be used with trusted code. The public API may change
before `1.0.0`.

Tool schemas are not just documentation. In MCP, OpenAI-style tool calling, and
agent frameworks, names, descriptions, and input schemas shape whether the model
chooses the right tool and fills arguments correctly.

## Install

```bash
pip install mcp-toolsmith
```

For local development:

```bash
python -m pip install -e ".[dev]"
```

## Why?

LLM agents often fail because tool metadata is ambiguous.

Bad tool:

```python
def run(query: str):
    """Run operation."""
    return query
```

Audit:

```bash
mcp-toolsmith audit tools.py --execute --all-public
```

Output:

```text
WARNING name.vague: Tool name is too generic for reliable tool selection.
WARNING description.too_short: Tool description is too short to guide model selection.
WARNING schema.arg_description_missing: Argument descriptions are missing for: query.
```

## Usage

### Audit JSON tool definitions

JSON tool definitions are safe by default:

```bash
mcp-toolsmith audit tools.json
```

Example JSON input:

```json
{
  "tools": [
    {
      "name": "search_docs",
      "description": "Search project documentation by natural language query.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Question or topic to search for."
          },
          "limit": {
            "type": "integer",
            "description": "Maximum number of results to return.",
            "default": 5
          }
        },
        "required": ["query"]
      }
    }
  ]
}
```

Example audit output:

```text
OK Audited 1 tool(s) from tools.json
Errors: 0  Warnings: 0

search_docs [mcp] ~55 schema tokens
  No findings
```

### Compile tools

Compile to MCP-style tool definitions:

```bash
mcp-toolsmith compile tools.json --target mcp
```

Compile to OpenAI-style function definitions:

```bash
mcp-toolsmith compile tools.json --target openai
```

### Audit trusted Python files

Python files are executable source code, so `mcp-toolsmith` refuses to import
them unless you opt in:

```bash
mcp-toolsmith audit tools.py --execute
mcp-toolsmith compile tools.py --target mcp --execute
```

Use `--execute` only for trusted files.

By default, Python discovery only includes functions decorated with `@tool`:

```python
from mcp_toolsmith import tool


@tool
def search_docs(query: str, limit: int = 5) -> list[str]:
    """Search project documentation by natural language query.

    Args:
        query: Question or topic to search for.
        limit: Maximum number of results to return.
    """
    return []
```

Use decorator arguments to override the generated tool name or description:

```python
from mcp_toolsmith import tool


@tool(
    name="search_project_docs",
    description="Search project docs and return matching document IDs.",
)
def search_docs(query: str, limit: int = 5) -> list[str]:
    """Search project documentation by natural language query."""
    return []
```

Use `--all-public` to include every public top-level function and Pydantic model:

```bash
mcp-toolsmith audit tools.py --execute --all-public
mcp-toolsmith compile tools.py --target mcp --execute --all-public
```

`--all-public` is mainly a compatibility path for early alpha behavior. For new
Python tool files, prefer `@tool`.

More copy-pasteable examples live in [examples](examples/).

## Python API

```python
from mcp_toolsmith import audit_file, compile_file

report = audit_file("tools.json")
report.print()

mcp_tools = compile_file("tools.json", target="mcp")
openai_tools = compile_file("tools.json", target="openai")
```

For trusted Python files:

```python
report = audit_file("tools.py", execute=True)
mcp_tools = compile_file("tools.py", target="mcp", execute=True)
```

To opt into broad Python discovery:

```python
report = audit_file("tools.py", execute=True, all_public=True)
mcp_tools = compile_file("tools.py", target="mcp", execute=True, all_public=True)
```

## Checks

| Check | Why it matters |
| --- | --- |
| Vague tool names | Agents may pick the wrong tool when names are generic |
| Missing descriptions | Tool selection depends heavily on clear descriptions |
| Missing argument descriptions | Models need argument-level context |
| Oversized schemas | Large schemas cost tokens and can distract smaller models |
| Overlapping tools | Similar tools make tool choice unstable |
| Tool-poisoning language | Tool metadata is part of the prompt surface |

## Roadmap

| Version | Goal |
| --- | --- |
| `0.2.0` | Decorator-based Python tool discovery |
| `0.3.0` | OpenAPI input and richer JSON Schema validation |
| `0.4.0` | Provider compatibility profiles for Anthropic, Gemini, and OpenAI |
| `0.5.0` | Deterministic schema compaction and rewriting |
| `1.0.0` | Stable public API and compatibility matrix |

## License

MIT

