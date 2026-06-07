from pathlib import Path

Path("should_not_exist.txt").write_text("executed", encoding="utf-8")


def search_docs(query: str) -> str:
    """Search documentation for a specific user question.

    Args:
        query: Question or topic to search for.
    """
    return query

