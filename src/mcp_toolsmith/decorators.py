from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def tool(
    func: F | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> F | Callable[[F], F]:
    """Mark a function as an LLM-callable tool."""

    def decorate(inner: F) -> F:
        inner.__mcp_toolsmith_tool__ = {
            "name": name,
            "description": description,
        }
        return inner

    if func is None:
        return decorate
    return decorate(func)

