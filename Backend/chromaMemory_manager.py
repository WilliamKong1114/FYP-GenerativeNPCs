from __future__ import annotations

import uuid
import datetime
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Iterable, Optional, Tuple
from agent_memory import AgentMemoryManager
from chroma_client import get_client

memory_manager = AgentMemoryManager()

STANDARD_COLLECTIONS: Tuple[str, ...] = (
    "summary",
    "observation",
    "reflection",
)

""" LEGACY_COLLECTION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "summary": ("summaries", "memories", "memory"),
}"""

def _ensure_user_exists(user_id: str, path: str = "./chroma_db") -> None:
    """Auto-create a user_info row if the user is missing."""
    uid = (user_id or "").strip()
    if not uid:
        return

    client = get_client(path)
    user_col = client.get_or_create_collection("user_info")
    existing = user_col.get(ids=[uid], include=["documents"])
    ids = existing.get("ids", []) or []
    if ids:
        return

    user_col.upsert(
        ids=[uid],
        documents=[f"Auto-created agent user: {uid}"],
        metadatas=[
            {
                "type": "user_info",
                "user_id": uid,
                "created_at": datetime.datetime.utcnow().isoformat(),
                "auto_created": True,
            }
        ],
    )

def _chroma_sqlite_path(path: str) -> Path:
    return Path(path) / "chroma.sqlite3"

def _connect_chroma_sqlite(path: str) -> sqlite3.Connection:
    db = _chroma_sqlite_path(path)
    if not db.exists():
        raise FileNotFoundError(f"Chroma sqlite file not found: {db}")
    return sqlite3.connect(str(db))

def _load_collection_registry(path: str) -> Dict[str, Dict[str, Any]]:
    """Return collection registry keyed by collection UUID (folder name).

    Includes collection name, dimension, and any stored schema/config JSON strings.
    """
    con = _connect_chroma_sqlite(path)
    try:
        rows = con.execute(
            "SELECT id, name, dimension, database_id, config_json_str, schema_str FROM collections"
        ).fetchall()
    finally:
        con.close()

    reg: Dict[str, Dict[str, Any]] = {}
    for cid, name, dim, dbid, config_json_str, schema_str in rows:
        reg[str(cid)] = {
            "id": str(cid),
            "name": name,
            "dimension": dim,
            "database_id": dbid,
            "config_json_str": config_json_str,
            "schema_str": schema_str,
        }
    return reg

def _collection_counts(path: str) -> Dict[str, int]:
    """Count embeddings per collection using sqlite joins (fast, no full fetch)."""
    con = _connect_chroma_sqlite(path)
    try:
        rows = con.execute(
            """
            SELECT s.collection AS collection_id, COUNT(*) AS cnt
            FROM embeddings e
            JOIN segments s ON s.id = e.segment_id
            GROUP BY s.collection
            """
        ).fetchall()
    finally:
        con.close()
    return {str(cid): int(cnt) for cid, cnt in rows}

def _collection_metadata_schema(path: str) -> Dict[str, Dict[str, List[str]]]:
    """Infer metadata schema per collection from sqlite (keys + observed value types).

    Returns: {collection_id: {metadata_key: ["str", "int", ...]}}
    """
    con = _connect_chroma_sqlite(path)
    try:
        rows = con.execute(
            """
            SELECT
                s.collection AS collection_id,
                em.key,
                SUM(CASE WHEN em.string_value IS NOT NULL THEN 1 ELSE 0 END) AS string_cnt,
                SUM(CASE WHEN em.int_value IS NOT NULL THEN 1 ELSE 0 END) AS int_cnt,
                SUM(CASE WHEN em.float_value IS NOT NULL THEN 1 ELSE 0 END) AS float_cnt,
                SUM(CASE WHEN em.bool_value IS NOT NULL THEN 1 ELSE 0 END) AS bool_cnt
            FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            JOIN segments s ON s.id = e.segment_id
            GROUP BY s.collection, em.key
            """
        ).fetchall()
    finally:
        con.close()

    out: Dict[str, Dict[str, List[str]]] = {}
    for cid, key, string_cnt, int_cnt, float_cnt, bool_cnt in rows:
        types: List[str] = []
        if string_cnt:
            types.append("str")
        if int_cnt:
            types.append("int")
        if float_cnt:
            types.append("float")
        if bool_cnt:
            types.append("bool")
        out.setdefault(str(cid), {})[str(key)] = types
    return out

def list_vector_tables(path: str = "./chroma_db") -> List[Dict[str, Any]]:
    """List Chroma collections ("tables") with their UUID folder IDs and schema."""
    registry = _load_collection_registry(path)
    counts = _collection_counts(path)
    meta_schema = _collection_metadata_schema(path)

    results: List[Dict[str, Any]] = []
    for cid, info in sorted(registry.items(), key=lambda kv: (kv[1]["name"], kv[0])):
        results.append(
            {
                "collection_id": cid,
                "name": info.get("name"),
                "dimension": info.get("dimension"),
                "count": counts.get(cid, 0),
                "metadata_schema": meta_schema.get(cid, {}),
            }
        )
    return results

def _resolve_collection_name_from_identifier(identifier: str, path: str) -> str:
    """Resolve either a collection UUID (folder name) or a collection name to name."""
    identifier = (identifier or "").strip()
    if not identifier:
        raise ValueError("Empty collection identifier")

    registry = _load_collection_registry(path)
    if identifier in registry:
        return str(registry[identifier]["name"])

    # Match by name (case-sensitive first, then case-insensitive)
    for info in registry.values():
        if info.get("name") == identifier:
            return str(info["name"])
    lowered = identifier.lower()
    for info in registry.values():
        if str(info.get("name", "")).lower() == lowered:
            return str(info["name"])

    raise KeyError(f"No collection found for '{identifier}'")

def _format_metadata_schema(schema: Dict[str, List[str]]) -> str:
    if not schema:
        return "{}"
    parts = []
    for k in sorted(schema.keys()):
        t = "|".join(schema.get(k) or []) or "unknown"
        parts.append(f"{k}:{t}")
    return "{ " + ", ".join(parts) + " }"

def list_users_from_vector_metadata(
    path: str = "./chroma_db",
    collection_identifiers: Optional[Iterable[str]] = None,
) -> List[str]:
    """List distinct user_ids seen in Chroma embedding metadata (efficient, SQL-backed)."""
    registry = _load_collection_registry(path)

    collection_ids: List[str]
    if collection_identifiers:
        resolved_ids: List[str] = []
        for ident in collection_identifiers:
            ident = (ident or "").strip()
            if not ident:
                continue

            # If caller passes a logical table name, expand legacy aliases too.
            expanded_idents = [ident]
            #if ident in LEGACY_COLLECTION_ALIASES:
            #    expanded_idents.extend(list(LEGACY_COLLECTION_ALIASES.get(ident, ())))

            for expanded in expanded_idents:
                if expanded in registry:
                    resolved_ids.append(expanded)
                    continue
                # Resolve by name
                matched = [cid for cid, info in registry.items() if str(info.get("name", "")) == expanded]
                if not matched:
                    matched = [
                        cid
                        for cid, info in registry.items()
                        if str(info.get("name", "")).lower() == expanded.lower()
                    ]
                resolved_ids.extend(matched)
        collection_ids = sorted(set(resolved_ids))
    else:
        collection_ids = sorted(registry.keys())

    if not collection_ids:
        return []

    placeholders = ",".join(["?"] * len(collection_ids))
    con = _connect_chroma_sqlite(path)
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT em.string_value
            FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            JOIN segments s ON s.id = e.segment_id
            WHERE em.key='user_id'
              AND s.collection IN ({placeholders})
              AND em.string_value IS NOT NULL
            ORDER BY em.string_value
            """,
            collection_ids,
        ).fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows if r and r[0] is not None]

def ensure_standard_collections(path: str = "./chroma_db") -> None:
    client = get_client(path)
    for name in STANDARD_COLLECTIONS:
        client.get_or_create_collection(name)

def add_user_info(user_id: str, info: str, path: str = "./chroma_db") -> str:
    client = get_client(path)
    col = client.get_or_create_collection("user_info")
    col.upsert(ids=[user_id], documents=[info], metadatas=[{"type": "user_info", "user_id": user_id, "created_at": datetime.datetime.utcnow().isoformat()}])
    return f"Created user info for {user_id}"

def add_memories(docs: List[str], user_id: str, path: str = "./chroma_db", importance: int = 5, type: str = "summary", game_hour: int = 0) -> List[str]:

    client = get_client(path)
    _ensure_user_exists(user_id, path)
    col = client.get_or_create_collection(type)

    if not docs:
        return []

    ids = [str(uuid.uuid4()) for _ in docs]
    metas = [{
        "type": type,
        "user_id": user_id,
        "importance": importance,
        "created_at": game_hour,
        "modified_on": game_hour,
    } for _ in docs]
    col.add(ids=ids, documents=docs, metadatas=metas)
    return ids

def _get_collection_memories( collection_name: str, query: Any, user_id: str, current_hours: int, partner_id: Optional[str] = None, path: str = "./chroma_db", target_count: int = 10, top_k: int = 5) -> str:
    """Retrieve memories from a single collection using recency/importance/relevance scoring."""
    try:
        query_text = " ".join(query) if isinstance(query, list) else str(query)
        query_text = query_text.strip()
        if not query_text:
            return "No memories found."

        client = get_client(path)
        results = client.get_or_create_collection(collection_name).query(
            query_texts=[query_text],
            n_results=target_count,
            where={"user_id": user_id},
        )

        docs = (results.get("documents") or [[]])[0] or []
        metas = (results.get("metadatas") or [[]])[0] or []
        dists = (results.get("distances") or [[]])[0] or []

        if not docs:
            return "No memories found."

        retrieved_memories: List[Tuple[str, float]] = []
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            relevance = 1.0 / (1.0 + float(dist))
            importance = float(meta.get("importance", 3)) / 10.0

            last_accessed = int(meta.get("modified_on", 0) or 0)
            delta_t = max(0, int(current_hours) - last_accessed)
            recency = pow(0.99, delta_t)

            final_score = (0.5 * recency) + (0.3 * importance) + (0.2 * relevance)
            if partner_id and str(partner_id).strip() and str(partner_id).lower() in str(doc).lower():
                final_score *= 1.5

            retrieved_memories.append((str(doc), final_score))

        retrieved_memories.sort(key=lambda x: x[1], reverse=True)
        top_memories = [m[0] for m in retrieved_memories[:top_k]]
        return f"\nRelevant memories: {top_memories}"
    except Exception as e:
        print(f"Error retrieving {collection_name} memory context: {e}")
        return ""

def get_reflection(query: Any, user_id: str, current_hours: int, partner_id: Optional[str] = None, path: str = "./chroma_db") -> str:
    return _get_collection_memories("reflection", query, user_id, current_hours, partner_id, path)

def get_observation(query: Any, user_id: str, current_hours: int, partner_id: Optional[str] = None, path: str = "./chroma_db") -> str:
    return _get_collection_memories("observation", query, user_id, current_hours, partner_id, path)

def get_summary(query: Any, user_id: str, current_hours: int, partner_id: Optional[str] = None, path: str = "./chroma_db") -> str:
    return _get_collection_memories("summary", query, user_id, current_hours, partner_id, path)

def delete_user(user_id: str, path: str = "./chroma_db") -> str:
    client = get_client(path)
    col = client.get_or_create_collection("user_info")
    try:
        col.delete(ids=[user_id])
    except Exception as e:
        return f"Error deleting user info for {user_id}: {e}"

    delete_memories_for_user(user_id, path)
    delete_conversations_for_user(user_id, path)
    return f"Deleted user {user_id} from db"

def delete_memories_for_user(user_id: str, path: str = "./chroma_db") -> str:
    client = get_client(path)
    deleted_from = []
    errors = []
    #collection_names = list(STANDARD_COLLECTIONS) + list(LEGACY_COLLECTION_ALIASES.get("summary", ()))
    collection_names = list(STANDARD_COLLECTIONS)

    for name in sorted(set(collection_names)):
        try:
            col = client.get_or_create_collection(name)
            col.delete(where={"user_id": user_id})
            deleted_from.append(name)
        except Exception as e:
            errors.append(f"{name}: {e}")

    if errors and not deleted_from:
        return f"Error deleting vector records for user {user_id}: {'; '.join(errors)}"
    return f"Deleted vector records for {user_id} from: {', '.join(deleted_from)}"

def clear_collection_data(identifier: str, path: str = "./chroma_db") -> str:
    """Clear all records inside a specific collection (keep the collection itself)."""
    client = get_client(path)
    collection_name = _resolve_collection_name_from_identifier(identifier, path)
    col = client.get_collection(collection_name)

    rows = col.get()
    ids = rows.get("ids", []) or []
    if not ids:
        return f"Collection '{collection_name}' is already empty."

    batch_size = 1000
    for start in range(0, len(ids), batch_size):
        col.delete(ids=ids[start:start + batch_size])

    return f"Cleared {len(ids)} record(s) from collection '{collection_name}'."

def delete_collection(identifier: str, path: str = "./chroma_db") -> str:
    """Delete a specific collection entirely."""
    client = get_client(path)
    collection_name = _resolve_collection_name_from_identifier(identifier, path)
    client.delete_collection(collection_name)
    return f"Deleted collection '{collection_name}'."

def manage_collection(identifier: str, action: str, path: str = "./chroma_db") -> str:
    action = (action or "").strip().lower()
    if action == "clear":
        return clear_collection_data(identifier, path)
    if action == "delete":
        return delete_collection(identifier, path)
    return "Invalid action. Use 'clear' or 'delete'."

def delete_conversations_for_user(user_id: str, path: str = "./chroma_db") -> str:
    client = get_client(path)
    try:
        col = client.get_collection("conversations")
    except Exception:
        return f"No conversations found for {user_id}"
        
    try:
        col.delete(where={"user_id": user_id})
        return f"Deleted conversations for {user_id}"
    except Exception as e:
        return f"Error deleting conversations for user {user_id}: {e}"

def list_users_with_memories(path: str = "./chroma_db") -> List[Dict[str, Any]]:
    ensure_standard_collections(path)
    client = get_client(path)
    user_col = client.get_or_create_collection("user_info")

    users_data = user_col.get(include=["documents", "metadatas"])
    user_ids = users_data.get("ids", []) or []
    user_docs = users_data.get("documents", []) or []
    user_info_map = {uid: doc for uid, doc in zip(user_ids, user_docs)}

    vector_users = set(list_users_from_vector_metadata(path, collection_identifiers=STANDARD_COLLECTIONS))
    all_known_uids = set(user_ids) | vector_users

    registry = _load_collection_registry(path)
    name_to_id = {info["name"]: cid for cid, info in registry.items()}
    name_to_logical: Dict[str, str] = {}
    for logical in STANDARD_COLLECTIONS:
        name_to_logical[logical] = logical
        #for alias in LEGACY_COLLECTION_ALIASES.get(logical, ()):
        #    name_to_logical[alias] = logical

    candidate_names: List[str] = []
    for logical in STANDARD_COLLECTIONS:
        candidate_names.append(logical)
        #candidate_names.extend(list(LEGACY_COLLECTION_ALIASES.get(logical, ())))

    table_ids = [name_to_id.get(n) for n in candidate_names if name_to_id.get(n)]

    per_user_counts: Dict[str, Dict[str, int]] = {uid: {t: 0 for t in STANDARD_COLLECTIONS} for uid in all_known_uids}
    if table_ids:
        placeholders = ",".join(["?"] * len(table_ids))
        con = _connect_chroma_sqlite(path)
        try:
            rows = con.execute(
                f"""
                SELECT s.collection AS collection_id, em.string_value AS user_id, COUNT(*) AS cnt
                FROM embedding_metadata em
                JOIN embeddings e ON e.id = em.id
                JOIN segments s ON s.id = e.segment_id
                WHERE em.key='user_id'
                  AND em.string_value IS NOT NULL
                  AND s.collection IN ({placeholders})
                GROUP BY s.collection, em.string_value
                """,
                table_ids,
            ).fetchall()
        finally:
            con.close()

        id_to_name = {cid: info["name"] for cid, info in registry.items()}
        for cid, uid, cnt in rows:
            raw_table_name = id_to_name.get(str(cid))
            logical_table = name_to_logical.get(str(raw_table_name), str(raw_table_name))
            if logical_table in STANDARD_COLLECTIONS and uid in per_user_counts:
                per_user_counts[uid][logical_table] = per_user_counts[uid].get(logical_table, 0) + int(cnt)

    results: List[Dict[str, Any]] = []
    for uid in sorted(all_known_uids):
        results.append(
            {
                "user_id": uid,
                "description": user_info_map.get(uid, "No description found in user_info"),
                "counts": per_user_counts.get(uid, {t: 0 for t in STANDARD_COLLECTIONS}),
            }
        )
    return results

def main() -> None:
    ensure_standard_collections()
    menu_options = {
        "1": {
            "description": "Clear memories for a user",
            "function": lambda: delete_memories_for_user(input("User id: ")),
            "print_result": lambda result: print(result),
        },
        "2": {
            "description": "Create new user",
            "function": lambda: add_user_info(input("User id: "), input("User info text: ")),
            "print_result": lambda result: print(result),
        },
        "3": {
            "description": "Delete a user",
            "function": lambda: delete_user(input("User id: ")),
            "print_result": lambda result: print(result),
        },
        "4": {
            "description": "List users + per-table counts (summary/observation/reflection)",
            "function": lambda: list_users_with_memories(),
            "print_result": lambda users: [
                print(
                    "User ID: {uid}\nDescription: {desc}\nCounts: {counts}\n".format(
                        uid=u.get("user_id"),
                        desc=u.get("description"),
                        counts=u.get("counts"),
                    )
                )
                for u in users
            ],
        },
        "5": {
            "description": "List collections (UUID folder id + schema)",
            "function": lambda: list_vector_tables(),
            "print_result": lambda tables: [
                print(
                    "Name: {name}\nCollection ID (folder): {cid}\nCount: {cnt}\nMetadata schema: {schema}\n".format(
                        name=t.get("name"),
                        cid=t.get("collection_id"),
                        cnt=t.get("count"),
                        schema=_format_metadata_schema(t.get("metadata_schema") or {}),
                    )
                )
                for t in tables
            ],
        },
        "6": {
            "description": "List data schema of a table by name or UUID",
            "function": lambda: (lambda ident: [t for t in list_vector_tables() if t["name"] == _resolve_collection_name_from_identifier(ident, "./chroma_db")][0])(
                input("Enter collection name or UUID").strip()
            ),
            "print_result": lambda t: print(
                "Name: {name}\nCollection ID: {cid}\nDimension: {dim}\nCount: {cnt}\nMetadata schema: {schema}\n".format(
                    name=t.get("name"),
                    cid=t.get("collection_id"),
                    dim=t.get("dimension"),
                    cnt=t.get("count"),
                    schema=t.get("metadata_schema"),
                )
            ),
        },
        "7": {
            "description": "Collection maintenance (clear data or delete collection)",
            "function": lambda: (
                (lambda ident, action: (
                    manage_collection(ident, action)
                    if action.lower() != "delete"
                    else (
                        manage_collection(ident, action)
                        if input("Type DELETE to confirm collection deletion: ").strip() == "DELETE"
                        else "Collection deletion canceled."
                    )
                ))(
                    input("Enter collection name or UUID: ").strip(),
                    input("Action ('clear' or 'delete'): ").strip(),
                )
            ),
            "print_result": lambda result: print(result),
        }
    }

    while True:
        try:
            menu_text = "\nChromaDB Data Manager\n" + "\n".join(f"{key}) {opt['description']}" for key, opt in menu_options.items()) + "\nChoose (or 'exit' to quit): "
            choice = input(menu_text).strip()

            if not choice:
                continue
            if choice.lower() == "exit":
                break
            if choice in menu_options:
                result = menu_options[choice]["function"]()
                menu_options[choice]["print_result"](result)
            else:
                print("Invalid choice. Try again.")    
                    
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Error: {e}")
            continue

if __name__ == "__main__":
    main()