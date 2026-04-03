"""
rag.py — RAG (Retrieval-Augmented Generation) system for Axon.
Uses ChromaDB to index local folders and retrieve relevant
document chunks when the user asks questions.
"""

import os
import hashlib
from core.files import extract_text

# Lazy-initialised globals
_client = None
_collection = None
_COLLECTION_NAME = "axon_documents"

CHUNK_WORDS = 500
CHUNK_OVERLAP = 50


def _get_vector_dir():
    """Return absolute path to vector store directory."""
    from config import Config
    return Config.VECTOR_STORE_FOLDER


def _get_collection():
    """Get or create the ChromaDB collection (lazy init)."""
    global _client, _collection
    if _collection is not None:
        return _collection

    import chromadb
    from chromadb.utils import embedding_functions

    vec_dir = _get_vector_dir()
    os.makedirs(vec_dir, exist_ok=True)

    _client = chromadb.PersistentClient(path=vec_dir)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
    )
    _collection = _client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=ef,
    )
    return _collection


def _chunk_text(text):
    """Split text into overlapping word-based chunks."""
    words = text.split()
    if len(words) <= CHUNK_WORDS:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + CHUNK_WORDS
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += CHUNK_WORDS - CHUNK_OVERLAP
    return chunks


def _file_id(folder_path, file_path):
    """Deterministic ID for a chunk based on folder + file path + chunk index."""
    rel = os.path.relpath(file_path, folder_path)
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]


def index_folder(folder_path, progress_callback=None):
    """
    Index all supported documents in a folder into ChromaDB.
    Returns dict with count of files indexed and total chunks.
    """
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        return {"error": "Folder does not exist", "folder": folder_path}

    col = _get_collection()

    # Remove existing entries for this folder first
    _remove_folder_docs(folder_path, col)

    supported_ext = {
        ".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".xml",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".rst", ".tex",
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
        ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb",
        ".php", ".swift", ".kt", ".lua", ".r", ".sh", ".sql",
    }

    files_indexed = 0
    total_chunks = 0

    for root, dirs, files in os.walk(folder_path):
        # Skip hidden directories and common noise
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {
            "node_modules", "__pycache__", ".git", "venv", ".venv",
        }]

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supported_ext:
                continue

            fpath = os.path.join(root, fname)
            try:
                text, _ = extract_text(fpath)
            except Exception:
                continue

            if not text.strip():
                continue

            chunks = _chunk_text(text)
            base_id = _file_id(folder_path, fpath)
            rel_path = os.path.relpath(fpath, folder_path)

            for i, chunk in enumerate(chunks):
                doc_id = "%s_%04d" % (base_id, i)
                col.add(
                    ids=[doc_id],
                    documents=[chunk],
                    metadatas=[{
                        "folder": folder_path,
                        "file": rel_path,
                        "chunk_index": i,
                    }],
                )

            files_indexed += 1
            total_chunks += len(chunks)

            if progress_callback:
                progress_callback(files_indexed, fname)

    return {
        "folder": folder_path,
        "files_indexed": files_indexed,
        "total_chunks": total_chunks,
    }


def query_documents(query, n_results=5):
    """Query indexed documents for relevant chunks. Returns list of dicts."""
    col = _get_collection()
    if col.count() == 0:
        return []

    results = col.query(query_texts=[query], n_results=min(n_results, col.count()))

    docs = []
    for i in range(len(results["ids"][0])):
        docs.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i] if results.get("distances") else None,
        })
    return docs


def get_indexed_folders():
    """List all currently indexed folders with file counts."""
    col = _get_collection()
    if col.count() == 0:
        return []

    # Get all unique folders from metadata
    all_meta = col.get(include=["metadatas"])
    folder_stats = {}
    for meta in all_meta["metadatas"]:
        folder = meta.get("folder", "unknown")
        fname = meta.get("file", "")
        if folder not in folder_stats:
            folder_stats[folder] = {"folder": folder, "files": set(), "chunks": 0}
        folder_stats[folder]["files"].add(fname)
        folder_stats[folder]["chunks"] += 1

    result = []
    for folder, stats in folder_stats.items():
        result.append({
            "folder": folder,
            "file_count": len(stats["files"]),
            "chunk_count": stats["chunks"],
        })
    return result


def remove_folder(folder_path):
    """Remove a folder's documents from the index."""
    folder_path = os.path.abspath(folder_path)
    col = _get_collection()
    _remove_folder_docs(folder_path, col)
    return {"removed": folder_path}


def _remove_folder_docs(folder_path, col):
    """Remove all documents belonging to a folder."""
    if col.count() == 0:
        return
    # ChromaDB where filter on metadata
    try:
        col.delete(where={"folder": folder_path})
    except Exception:
        # Fallback: get matching IDs and delete them
        all_data = col.get(include=["metadatas"])
        ids_to_remove = []
        for i, meta in enumerate(all_data["metadatas"]):
            if meta.get("folder") == folder_path:
                ids_to_remove.append(all_data["ids"][i])
        if ids_to_remove:
            col.delete(ids=ids_to_remove)


# ── Roblox Docs Collection ─────────────────────────────

_ROBLOX_COLLECTION_NAME = "roblox_docs"
_roblox_collection = None


def _get_roblox_collection():
    """Get or create the dedicated Roblox docs ChromaDB collection (lazy init)."""
    global _roblox_collection, _client
    if _roblox_collection is not None:
        return _roblox_collection

    # Ensure the main client is initialised first (reuse it)
    _get_collection()

    from chromadb.utils import embedding_functions
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
    )
    _roblox_collection = _client.get_or_create_collection(
        name=_ROBLOX_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    return _roblox_collection


def index_roblox_docs(docs_folder: str, progress_callback=None):
    """
    Index .md, .html, and .txt files from a local Roblox Creator Docs copy.
    Call once via scripts/index_roblox_docs.py — not on every startup.
    Returns dict with files_indexed and total_chunks.
    """
    docs_folder = os.path.abspath(docs_folder)
    if not os.path.isdir(docs_folder):
        return {"error": "Folder does not exist", "folder": docs_folder}

    col = _get_roblox_collection()
    supported_ext = {".md", ".html", ".txt", ".rst"}
    files_indexed = 0
    total_chunks = 0

    for root, dirs, files in os.walk(docs_folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {
            "node_modules", "__pycache__", ".git",
        }]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supported_ext:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            if not content.strip():
                continue

            chunks = _chunk_text(content)
            base_id = hashlib.sha256(
                os.path.relpath(fpath, docs_folder).encode("utf-8")
            ).hexdigest()[:16]

            for i, chunk in enumerate(chunks):
                doc_id = "roblox_%s_%04d" % (base_id, i)
                col.upsert(
                    ids=[doc_id],
                    documents=[chunk],
                    metadatas=[{
                        "source": os.path.relpath(fpath, docs_folder),
                        "type": "roblox_docs",
                    }],
                )

            files_indexed += 1
            total_chunks += len(chunks)

            if progress_callback:
                progress_callback(files_indexed, fname)

    return {
        "folder": docs_folder,
        "files_indexed": files_indexed,
        "total_chunks": total_chunks,
    }


def query_roblox_docs(query: str, n_results: int = 5) -> list:
    """Semantic search over indexed Roblox Creator Documentation."""
    col = _get_roblox_collection()
    if col.count() == 0:
        return []
    results = col.query(
        query_texts=[query],
        n_results=min(n_results, col.count()),
    )
    if not results.get("documents") or not results["documents"][0]:
        return []
    return results["documents"][0]


def get_roblox_docs_stats() -> dict:
    """Return chunk count for the roblox_docs collection."""
    col = _get_roblox_collection()
    return {"collection": _ROBLOX_COLLECTION_NAME, "chunks": col.count()}
