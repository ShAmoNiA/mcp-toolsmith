from mcp_toolsmith import tool


@tool
def search_docs(query: str, limit: int = 5) -> list[str]:
    """Search project documentation by natural language query.

    Args:
        query: Question or topic to search for.
        limit: Maximum number of results to return.
    """
    return []


def normalize_query(query: str) -> str:
    """Normalize helper input."""
    return query.strip().lower()

