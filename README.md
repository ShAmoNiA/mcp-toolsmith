# mcp-toolsmith

Audit and compile Python tool schemas for LLM agents.

**Alpha:** JSON tools are safe by default. Python files require `--execute` and
should only be used with trusted code.

`mcp-toolsmith` is a small Python-first CLI and library for checking whether tool
metadata is usable by LLM agents, then compiling those tools into MCP or
OpenAI-style tool definitions.

## Install

```bash
pip install mcp-toolsmith==0.1.0a1
```

For local development:

```bash
python -m pip install -e ".[dev]"
```

## Usage

JSON tool definitions are safe by default:

```bash
mcp-toolsmith audit tools.json
mcp-toolsmith compile tools.json --target mcp
mcp-toolsmith compile tools.json --target openai
```

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

## What It Checks

| Check | Why it matters |
| --- | --- |
| Vague tool names | Agents pick the wrong tool when names are generic |
| Missing descriptions | Tool selection depends heavily on descriptions |
| Missing argument descriptions | Models need argument-level context |
| Oversized schemas | Large schemas cost tokens and distract smaller models |
| Overlapping tools | Similar tools make tool choice unstable |
| Tool-poisoning language | Tool metadata is part of the prompt surface |

## Release Roadmap

| Version | Goal |
| --- | --- |
| `0.1.0a1` | Safe-by-default CLI, Python/Pydantic discovery behind `--execute`, audit report, MCP/OpenAI compile |
| `0.2.0` | OpenAPI input and richer JSON Schema validation |
| `0.3.0` | Provider compatibility profiles for Anthropic/Gemini/OpenAI |
| `0.4.0` | Deterministic schema compaction and rewriting |
| `0.5.0` | GitHub Action for schema linting in CI |
| `1.0.0` | Stable public API and compatibility matrix |

## Publishing

Build locally:

```bash
python -m build
twine check dist/*
```

Publish to TestPyPI first:

```bash
twine upload --repository testpypi dist/*
```

When the test install works, publish the same artifacts to PyPI:

```bash
twine upload dist/*
```
