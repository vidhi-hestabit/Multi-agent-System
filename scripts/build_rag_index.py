"""
Run this ONCE before starting the RAG agent to build the FAISS index.
Usage: python scripts/build_rag_index.py
"""
import os
import pickle
import numpy as np

INDEX_PATH = os.environ.get("FAISS_INDEX_PATH", "data/indian_law.faiss")
CHUNKS_PATH = os.environ.get("FAISS_CHUNKS_PATH", "data/indian_law_chunks.pkl")
CHUNK_SIZE = 500


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def main():
    os.makedirs("data", exist_ok=True)

    print("Loading dataset from Hugging Face...")
    from datasets import load_dataset
    dataset = load_dataset("viber1/indian-law-dataset", split="train")

    print(f"Loaded {len(dataset)} records. Chunking...")
    chunks = []
    for row in dataset:
        instruction = row.get("Instruction", "").strip()
        response = row.get("Response", "").strip()
        if response:
            combined = f"Q: {instruction}\nA: {response}" if instruction else response
            chunks.extend(chunk_text(combined))

    print(f"Created {len(chunks)} chunks. Embedding with sentence-transformers...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(chunks, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
    embeddings = np.array(embeddings).astype(np.float32)

    print("Building FAISS index...")
    import faiss
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, INDEX_PATH)
    with open(CHUNKS_PATH, "wb") as f:
        pickle.dump(chunks, f)

    print(f"Done. Index saved to {INDEX_PATH} ({len(chunks)} chunks).")


if __name__ == "__main__":
    main()
