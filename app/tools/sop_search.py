"""SOP retrieval tool wrapping the RAG index."""

from __future__ import annotations

from typing import Any

from app.rag.index import retrieve_sops


def search_sops(defect_type: str, extra_context: str = "", top_k: int | None = None) -> list[dict[str, Any]]:
    """Build a query from defect type / context and retrieve SOP chunks."""
    query = f"paint quality defect {defect_type.replace('_', ' ')} {extra_context}".strip()
    return retrieve_sops(query, top_k=top_k)
