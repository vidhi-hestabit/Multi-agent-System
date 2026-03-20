from __future__ import annotations
import pickle
import numpy as np
from common.config import get_settings
from common.logging import get_logger
from mcp_server.app import mcp

logger = get_logger(__name__)

TOOL_NAME = "query_rag"
TOOL_DESCRIPTION = "Search the Indian Law dataset using semantic similarity and return relevant legal text chunks."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The legal question or search query",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of top results to return",
            "default": 5,
        },
    },
    "required": ["query"],
}

_index = None
_chunks: list[str] = []


def _load_index():
    global _index, _chunks
    if _index is not None:
        return
    try:
        import faiss
        settings = get_settings()
        _index = faiss.read_index(settings.faiss_index_path)
        with open(settings.faiss_chunks_path, "rb") as f:
            _chunks = pickle.load(f)
        logger.info("rag_index_loaded", chunks=len(_chunks))
    except Exception as exc:
        logger.error("rag_index_load_failed", error=str(exc))
        _index = None
        _chunks = []


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(query: str, top_k: int = 5) -> dict:
    _load_index()

    if _index is None or not _chunks:
        return {"error": "RAG index not available. Run build_rag_index.py first.", "chunks": []}

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        query_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)

        import faiss
        distances, indices = _index.search(query_vec, top_k)
        results = [_chunks[i] for i in indices[0] if i < len(_chunks)]
        return {"chunks": results, "total": len(results)}
    except Exception as exc:
        logger.error("rag_search_failed", error=str(exc))
        return {"error": str(exc), "chunks": []}