import os
import re
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List


MEMORY_FILE_PATH = "data/historical_incidents/memory.md"
VECTOR_DB_DIR = "data/vectordb"
COLLECTION_NAME = "clawops_incident_memory"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


DEFAULT_MEMORY = """# Production Incident Memory

## Incident INC-2026-05A
- Type: CRASH_LOOP_BACKOFF
- Symptoms: Pod restarted repeatedly after invalid environment configuration.
- Resolution: Validate deployment environment variables and config maps.

## Incident INC-2026-05B
- Type: DB_POOL_EXHAUSTED
- Symptoms: HikariPool returned timeout after 30000ms while waiting for a DB connection.
- Resolution: Increased max pool size and added connection leak detection.
"""


def _ensure_memory_file() -> None:
    if os.path.exists(MEMORY_FILE_PATH):
        return

    os.makedirs(os.path.dirname(MEMORY_FILE_PATH), exist_ok=True)
    with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(DEFAULT_MEMORY)


def load_historical_memory() -> str:
    """Load raw markdown memory for migration/bootstrap into ChromaDB."""
    _ensure_memory_file()
    with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _split_incidents(memory_content: str) -> List[str]:
    sections = re.split(r"(?m)^##\s+", memory_content)
    incidents: List[str] = []

    for section in sections[1:]:
        cleaned = section.strip()
        if cleaned:
            incidents.append("## " + cleaned)

    return incidents


def _incident_id_from_text(text: str, fallback_index: int) -> str:
    match = re.search(r"\bINC-[A-Za-z0-9-]+", text)
    if match:
        return match.group(0)
    return f"legacy-memory-{fallback_index}"


def _flatten_values(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        chunks: List[str] = []
        for item in value.values():
            chunks.extend(_flatten_values(item))
        return chunks
    if isinstance(value, list):
        chunks = []
        for item in value:
            chunks.extend(_flatten_values(item))
        return chunks
    return [str(value)]


def build_incident_query(
    alert: Dict[str, Any],
    logs: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    k8s_events: List[Dict[str, Any]],
) -> str:
    fields = []
    fields.extend(_flatten_values(alert))
    fields.extend(_flatten_values(logs))
    fields.extend(_flatten_values(metrics))
    fields.extend(_flatten_values(k8s_events))
    return " ".join(fields)


@lru_cache(maxsize=1)
def _embedding_model():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache(maxsize=1)
def _collection():
    import chromadb

    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=VECTOR_DB_DIR)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _safe_embed_documents(documents: List[str]) -> List[List[float]]:
    return _embedding_model().embed_documents(documents)


def _safe_embed_query(query: str) -> List[float]:
    return _embedding_model().embed_query(query)


def _bootstrap_legacy_memory() -> None:
    collection = _collection()

    if collection.count() > 0:
        return

    incidents = _split_incidents(load_historical_memory())
    if not incidents:
        return

    ids = [_incident_id_from_text(incident, index) for index, incident in enumerate(incidents)]
    embeddings = _safe_embed_documents(incidents)
    metadatas = [
        {
            "incident_id": incident_id,
            "source": "legacy_memory_md",
            "recorded_at": "bootstrap",
        }
        for incident_id in ids
    ]

    collection.upsert(
        ids=ids,
        documents=incidents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def add_to_vector_db(incident_id: str, post_mortem_text: str) -> None:
    """Vectorize and persist a resolved incident into ChromaDB."""
    if not post_mortem_text.strip():
        return

    try:
        collection = _collection()
        embedding = _safe_embed_documents([post_mortem_text])[0]
        collection.upsert(
            ids=[incident_id],
            documents=[post_mortem_text],
            embeddings=[embedding],
            metadatas=[
                {
                    "incident_id": incident_id,
                    "source": "clawops_post_mortem",
                    "recorded_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ],
        )
    except Exception as exc:
        print(f"[WARN] Vector memory write failed: {exc}")


def semantic_search(alert_summary: str, top_k: int = 2) -> List[str]:
    """Query ChromaDB for the Top-K semantically similar historical incidents."""
    if not alert_summary.strip():
        return []

    try:
        _bootstrap_legacy_memory()
        collection = _collection()
        if collection.count() == 0:
            return []

        query_embedding = _safe_embed_query(alert_summary)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        matches: List[str] = []
        for document, distance, metadata in zip(documents, distances, metadatas):
            incident_id = metadata.get("incident_id", "unknown") if metadata else "unknown"
            similarity = 1.0 - float(distance)
            matches.append(
                f"[{incident_id}] similarity={similarity:.3f}\n{document}"
            )

        return matches
    except Exception as exc:
        print(f"[WARN] Vector memory search failed: {exc}")
        return []


def append_to_memory(incident_id: str, title: str, rca: str) -> None:
    """Persist a resolved incident in markdown and ChromaDB memory."""
    _ensure_memory_file()
    new_entry = (
        f"\n## Incident {incident_id}\n"
        f"- Title: {title}\n"
        f"- Root Cause Analysis: {rca}\n"
        f"- Recorded At: {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
    )

    with open(MEMORY_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(new_entry)

    add_to_vector_db(incident_id, new_entry)
