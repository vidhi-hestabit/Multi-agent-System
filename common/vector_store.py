from __future__ import annotations
import logging
import asyncio
import hashlib
import json
from typing import List, Dict, Any, Optional
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
from common.config import get_settings

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.pinecone_api_key
        self.index_name = settings.pinecone_index_name
        self.dimension = settings.pinecone_dimension
        
        if not self.api_key:
            logger.warning("Pinecone API key not set. Vector storage will be disabled.")
            self.pc = None
            self.index = None
        else:
            try:
                self.pc = Pinecone(api_key=self.api_key)
                self._ensure_index()
                self.index = self.pc.Index(self.index_name)
                logger.info(f"Pinecone index {self.index_name} initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Pinecone: {e}")
                self.pc = None
                self.index = None
            
        try:
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("SentenceTransformer model loaded")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None

    def _ensure_index(self):
        if not self.pc: return
        try:
            if self.index_name not in self.pc.list_indexes().names():
                self.pc.create_index(
                    name=self.index_name,
                    dimension=self.dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
        except Exception as e:
            logger.error(f"Error ensuring Pinecone index: {e}")

    def embed(self, text: str) -> List[float]:
        if not self.model: return []
        return self.model.encode(text).tolist()

    async def upsert_session(self, user_email: str, session_id: str, query: str, result: str, metadata: Optional[Dict] = None):
        if not self.index: return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(None, self.embed, f"User: {query}\nAssistant: {result}")
        msg_id = hashlib.md5(f"{session_id}:{query}:{result}".encode()).hexdigest()
        meta = {
            "user_email": user_email, 
            "session_id": session_id, 
            "query": query, 
            "result": result, 
            "text": f"User: {query}\nAssistant: {result}",
            "created_at": now
        }
        if metadata: meta.update(metadata)
        
        # Ensure all metadata values are Pinecone-compatible (no nested dicts)
        final_meta = {}
        for k, v in meta.items():
            if isinstance(v, dict):
                final_meta[k] = json.dumps(v)
            else:
                final_meta[k] = v

        try:
            self.index.upsert(vectors=[(msg_id, vector, final_meta)])
        except Exception as e:
            logger.error(f"Pinecone upsert failed: {e}")

    async def query_context(self, user_email: str, query: str, top_k: int = 5) -> str:
        if not self.index: return ""
        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(None, self.embed, query)
        try:
            results = self.index.query(vector=vector, top_k=top_k, filter={"user_email": {"$eq": user_email}}, include_metadata=True)
            contexts = [match.get("metadata", {}).get("text") for match in results.get("matches", []) if match.get("metadata", {}).get("text")]
            return "\n---\n".join(contexts) if contexts else ""
        except Exception as e:
            logger.error(f"Pinecone query failed: {e}")
            return ""

    async def get_session_history(self, session_id: str, limit: int = 100) -> List[Dict]:
        """Fetch all messages for a specific session from Pinecone, ordered by created_at."""
        if not self.index: return []
        
        try:
            # For metadata-only filtering, we still need a vector.
            # A zero vector can sometimes cause issues with cosine similarity.
            # Using a small non-zero vector.
            dummy_vec = [0.01] * self.dimension
            
            results = self.index.query(
                vector=dummy_vec,
                top_k=limit,
                filter={"session_id": {"$eq": session_id}},
                include_metadata=True
            )
            
            history = []
            for match in results.get("matches", []):
                meta = match.get("metadata", {})
                # De-serialize context_data if it was stringified
                context_data = meta.get("context_data", {})
                if isinstance(context_data, str) and (context_data.startswith("{") or context_data.startswith("[")):
                    try:
                        context_data = json.loads(context_data)
                    except:
                        pass

                history.append({
                    "query": meta.get("query", ""),
                    "result": meta.get("result", ""),
                    "agents_called": meta.get("agents_called", []),
                    "status": meta.get("status", "completed"),
                    "created_at": meta.get("created_at", ""),
                    "context_data": context_data
                })
            
            # Sort chronologically by created_at
            history.sort(key=lambda x: x.get("created_at", ""))
            return history
        except Exception as e:
            logger.error(f"Pinecone session history fetch failed: {e}")
            return []

_vector_store = None
def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None: _vector_store = VectorStore()
    return _vector_store
