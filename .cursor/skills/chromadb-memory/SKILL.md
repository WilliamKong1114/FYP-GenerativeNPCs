---
name: chromadb-memory
description: >-
  Manage ChromaDB vector memory for NPC observations, summaries, and reflections
  in the FYP simulation. Use when editing chroma_client.py, chromaMemory_manager.py,
  memory retrieval, collection setup, or Chroma SQLite maintenance in Backend/.
---

# ChromaDB Memory (chroma-core/chroma)

When you start following this skill, tell the user: I am using chromadb-memory

## Repository health (baseline met)

| Criterion | Status |
|-----------|--------|
| Stars / forks | 29,355 stars · 2,525 forks |
| License | Apache-2.0 |
| Last commit | Within 6 months |
| CI | PR and release workflows active; recent runs passing |
| Docs | README, Python client guide, collection/query examples |

Source: https://github.com/chroma-core/chroma

## When to apply

- Changes to `chroma_client.py` or `chromaMemory_manager.py`
- Adding collections (`summary`, `observation`, `reflection`, `user_info`)
- Tuning retrieval for conversation or planning context
- Debugging `chroma_db/` persistence or dimension mismatches

## Project architecture

| File | Role |
|------|------|
| `chroma_client.py` | Singleton `PersistentClient` factory with thread-safe cache |
| `chromaMemory_manager.py` | Collection registry, upsert/query helpers, SQLite introspection |
| `execute_plan.py` | `get_collection()` via `@lru_cache` for `user_info` |
| `chroma_db/` | On-disk persistence (committed; reset carefully) |

Standard collections: `summary`, `observation`, `reflection`, `user_info`.

## Client pattern (follow existing factory)

Always use `get_client()` — never instantiate `PersistentClient` in multiple places:

```python
from chroma_client import get_client

client = get_client(path="./chroma_db")
collection = client.get_or_create_collection("observation")
```

Settings in `chroma_client.py` use `allow_reset=False` and `is_persistent=True` — preserve these unless explicitly resetting dev data.

## Upsert and query conventions

### Metadata (required for filtering)

Every document needs consistent metadata keys:

```python
metadata = {
    "type": "observation",
    "user_id": user_id,
    "created_at": datetime.datetime.utcnow().isoformat(),
}
collection.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])
```

### Query with user scope

```python
results = collection.query(
    query_texts=[query],
    n_results=5,
    where={"user_id": user_id},
)
```

### ID strategy

Use stable, deterministic IDs when updating the same logical record; use `uuid4()` for append-only memories.

## Readability rules

1. **One function per operation** — `upsert_observation`, `query_recent_summaries`, not generic `do_chroma(op, ...)`.
2. **Type hints on returns** — `list[dict[str, Any]]` or small dataclasses for query results.
3. **Path via pathlib** — Match `chromaMemory_manager._chroma_sqlite_path` pattern.
4. **Auto-create users** — Call `_ensure_user_exists()` before first upsert for a new `user_id`.
5. **No raw SQL on Chroma tables** unless using existing registry helpers (`_load_collection_registry`); prefer the Python API.

## Error handling

```python
import chromadb

try:
    collection.upsert(...)
except chromadb.errors.ChromaError as exc:
    raise RuntimeError(f"Chroma upsert failed for {user_id}") from exc
```

## Performance notes for simulation

- Cache collection handles (`@lru_cache` or module-level dict) — already done in `execute_plan.py`.
- Limit `n_results` in hot paths (dialogue, routing) to control token load.
- Batch upserts when recording many observations in one tick.

## Reset and maintenance

```python
# Dev only — allow_reset must be enabled in client settings
# Prefer chromaMemory_manager helpers over manual folder deletion
```

Coordinate with SQLite `agent_memory.db` when clearing an agent — both stores may hold related data.

## Additional resources

- Chroma docs: https://docs.trychroma.com/
- Project files: `Backend/chroma_client.py`, `Backend/chromaMemory_manager.py`
