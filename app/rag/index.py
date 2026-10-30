"""LlamaIndex + Chroma index over synthetic paint SOP Markdown files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_DOC_ID_RE = re.compile(r"SOP-PAINT-\d+", re.IGNORECASE)

# Lightweight in-process fallback used when Chroma/embeddings unavailable in tests.
_MEMORY_CHUNKS: list[dict[str, Any]] = []


def _parse_doc_meta(path: Path, text: str) -> tuple[str, str]:
    doc_id_match = _DOC_ID_RE.search(path.stem) or _DOC_ID_RE.search(text)
    doc_id = doc_id_match.group(0).upper() if doc_id_match else path.stem
    title = path.stem.replace("_", " ")
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return doc_id, title


def _chunk_markdown(text: str, chunk_size: int = 600) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks or [text[:chunk_size]]


def _load_memory_chunks(sop_dir: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(sop_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_id, title = _parse_doc_meta(path, text)
        for idx, chunk in enumerate(_chunk_markdown(text)):
            chunks.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "chunk_id": f"{doc_id}#chunk-{idx}",
                    "text": chunk,
                    "score": None,
                }
            )
    return chunks


def build_sop_index(*, force: bool = False) -> dict[str, Any]:
    """
    Build (or rebuild) the local SOP vector index.

    Falls back to an in-memory keyword index when vector deps fail, so demo/tests
    remain usable without downloading embedding models in constrained environments.
    """
    global _MEMORY_CHUNKS
    settings = get_settings()
    sop_dir = Path(settings.sop_dir)
    chroma_dir = Path(settings.chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    _MEMORY_CHUNKS = _load_memory_chunks(sop_dir)
    vector_ok = False
    error: str | None = None

    try:
        from llama_index.core import Document, Settings, SimpleDirectoryReader, VectorStoreIndex
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        from llama_index.vector_stores.chroma import ChromaVectorStore
        import chromadb

        embed_model = HuggingFaceEmbedding(model_name=settings.embedding_model)
        Settings.embed_model = embed_model
        Settings.chunk_size = 512
        Settings.chunk_overlap = 50

        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection_name = "paintops_sops"
        if force:
            try:
                client.delete_collection(collection_name)
            except Exception:
                pass
        collection = client.get_or_create_collection(collection_name)
        vector_store = ChromaVectorStore(chroma_collection=collection)

        documents = SimpleDirectoryReader(str(sop_dir)).load_data()
        enriched: list[Document] = []
        for doc in documents:
            path = Path(doc.metadata.get("file_path", doc.metadata.get("filename", "unknown")))
            doc_id, title = _parse_doc_meta(path, doc.text or "")
            doc.metadata["doc_id"] = doc_id
            doc.metadata["title"] = title
            enriched.append(doc)

        splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
        VectorStoreIndex.from_documents(
            enriched,
            vector_store=vector_store,
            transformations=[splitter],
            show_progress=False,
        )
        vector_ok = True
        logger.info("Built Chroma SOP index at %s (%d docs)", chroma_dir, len(enriched))
    except Exception as exc:  # noqa: BLE001 — keep demo usable offline
        error = str(exc)
        logger.warning("Vector index unavailable; using memory fallback: %s", error)

    return {
        "documents": len(list(sop_dir.glob('*.md'))),
        "chunks": len(_MEMORY_CHUNKS),
        "vector_index": vector_ok,
        "error": error,
        "chroma_dir": str(chroma_dir),
    }


def _keyword_retrieve(query: str, top_k: int) -> list[dict[str, Any]]:
    global _MEMORY_CHUNKS
    if not _MEMORY_CHUNKS:
        settings = get_settings()
        _MEMORY_CHUNKS = _load_memory_chunks(Path(settings.sop_dir))

    tokens = {t.lower() for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) > 2}
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in _MEMORY_CHUNKS:
        text_l = (chunk["text"] + " " + chunk["doc_id"] + " " + chunk["title"]).lower()
        overlap = sum(1 for t in tokens if t in text_l)
        # Boost exact defect phrase matches common in demo queries.
        bonus = 0.0
        if "orange" in tokens and "peel" in tokens and "orange peel" in text_l:
            bonus += 2.0
        if "nozzle" in tokens and "nozzle" in text_l:
            bonus += 1.5
        if "booth" in tokens and "environment" in text_l:
            bonus += 1.0
        score = overlap + bonus
        if score > 0:
            item = dict(chunk)
            item["score"] = float(score)
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def retrieve_sops(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """
    Retrieve top-k synthetic SOP chunks for a query.

    Returns structured dicts: doc_id, title, chunk_id, text, score.
    Never invents procedures when empty.
    """
    settings = get_settings()
    k = top_k or settings.sop_top_k

    try:
        from llama_index.core import Settings, VectorStoreIndex
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        from llama_index.vector_stores.chroma import ChromaVectorStore
        import chromadb

        chroma_dir = Path(settings.chroma_dir)
        if not chroma_dir.exists():
            return _keyword_retrieve(query, k)

        embed_model = HuggingFaceEmbedding(model_name=settings.embedding_model)
        Settings.embed_model = embed_model
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_or_create_collection("paintops_sops")
        if collection.count() == 0:
            return _keyword_retrieve(query, k)

        vector_store = ChromaVectorStore(chroma_collection=collection)
        index = VectorStoreIndex.from_vector_store(vector_store)
        retriever = index.as_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(query)
        results: list[dict[str, Any]] = []
        for i, node_with_score in enumerate(nodes):
            node = node_with_score.node
            meta = node.metadata or {}
            results.append(
                {
                    "doc_id": meta.get("doc_id", "UNKNOWN"),
                    "title": meta.get("title", meta.get("file_name", "Untitled")),
                    "chunk_id": meta.get("chunk_id", f"vec-{i}"),
                    "text": node.get_content(),
                    "score": float(node_with_score.score)
                    if node_with_score.score is not None
                    else None,
                }
            )
        if results:
            return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector retrieve failed; keyword fallback: %s", exc)

    return _keyword_retrieve(query, k)
