# mcp-toolsmith

Audit and compile Python tool schemas for LLM agents.

**Alpha:** JSON tool files are safe by default. Python files require `--execute`
and should only be used with trusted code. The public API may change before
`1.0.0`.

`mcp-toolsmith` is a small Python-first CLI and library for checking whether tool
metadata is usable by LLM agents, then compiling those tools into MCP or
OpenAI-style tool definitions.

It helps catch problems such as vague tool names, missing descriptions,
oversized schemas, overlapping tools, and prompt-injection-like language inside
tool metadata.

## Install

```bash
pip install mcp-toolsmith
```

For local development:

```bash
python -m pip install -e ".[dev]"
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

Trusted Python files can contain top-level functions and Pydantic v2 models:

```python
from pydantic import BaseModel, Field


def get_weather(city: str, unit: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City and country, such as Madrid, Spain.
        unit: Temperature unit to return.
    """
    return "sunny"


class SearchDocsInput(BaseModel):
    """Search project documentation by natural language query."""

    query: str = Field(description="Question or topic to search for.")
    limit: int = Field(default=5, description="Maximum number of results.")
```

In this alpha, trusted Python discovery includes every public top-level function
and every public Pydantic model in the file. Decorator-based discovery is planned
for a later release.

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
| `0.1.0a1` | Safe-by-default CLI, Python/Pydantic discovery behind `--execute`, audit report, MCP/OpenAI compile |
| `0.2.0` | Decorator-based Python tool discovery |
| `0.3.0` | OpenAPI input and richer JSON Schema validation |
| `0.4.0` | Provider compatibility profiles for Anthropic, Gemini, and OpenAI |
| `0.5.0` | Deterministic schema compaction and rewriting |
| `1.0.0` | Stable public API and compatibility matrix |

## License

MIT

