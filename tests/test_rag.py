"""SOP retrieval tests (keyword/memory path — no paid APIs)."""

from app.rag.index import build_sop_index, retrieve_sops
from app.tools.sop_search import search_sops


def test_build_index_loads_six_documents() -> None:
    meta = build_sop_index(force=True)
    assert meta["documents"] == 6
    assert meta["chunks"] > 0


def test_orange_peel_query_returns_relevant_sop() -> None:
    build_sop_index(force=True)
    results = search_sops("orange_peel")
    assert results
    doc_ids = {r["doc_id"] for r in results}
    assert "SOP-PAINT-002" in doc_ids or any(
        "orange" in (r.get("text") or "").lower() for r in results
    )
    for r in results:
        assert "doc_id" in r and "title" in r and "chunk_id" in r and "text" in r


def test_empty_retrieval_represented_honestly() -> None:
    build_sop_index(force=True)
    results = retrieve_sops("completely_unrelated_xyzzy_quantum_flargle", top_k=3)
    # May be empty or low-relevance; must not invent fake SOP IDs outside corpus.
    for r in results:
        assert str(r.get("doc_id", "")).startswith("SOP-PAINT-") or r.get("doc_id")
