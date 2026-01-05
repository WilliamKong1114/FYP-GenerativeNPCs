from __future__ import annotations

import chromadb
import uuid
import json
import datetime
import time
import os
from typing import List, Dict, Any, Tuple, Optional
from agent_memory import get_or_create_user_id, init_db, add_message, recap

def get_client(path: str = "./chroma_db") -> chromadb.PersistentClient:
    """Return a PersistentClient connected to the local Chroma DB path."""
    return chromadb.PersistentClient(path=path)

def add_user_info(user_id: str, info: str, path: str = "./chroma_db") -> str:
    """Add a new user"""
    client = get_client(path)
    col = client.get_or_create_collection("user_info")
    col.upsert(ids=[user_id], documents=[info], metadatas=[{"type": "user_info", "user_id": user_id, "created_at": datetime.datetime.utcnow().isoformat()}])
    return f"Created user info for {user_id}"

def add_memories(docs: List[str], user_id: str = "default_user", path: str = "./chroma_db") -> List[str]:
    """Add new memories for a user"""
    client = get_client(path)
    col = client.get_or_create_collection("memories")
    # Guard against empty input which ChromaDB `add` does not accept
    if not docs:
        return []

    ids = [str(uuid.uuid4()) for _ in docs]
    metas = [{"type": "memory", "user_id": user_id} for _ in docs]
    col.add(ids=ids, documents=docs, metadatas=metas)
    return ids

def add_conversation_records(records: List[Dict[str, Any]], user_id: str = "default_user", path: str = "./chroma_db") -> List[str]:
    """Add conversation records for a user"""
    client = get_client(path)
    col = client.get_or_create_collection("conversations")
    # If there are no records, do not call ChromaDB.add (it requires non-empty lists)
    if not records:
        return []

    ids = [str(uuid.uuid4()) for _ in records]
    docs = [json.dumps(record) for record in records]
    metas = [{"type": "conversation", "user_id": user_id} for _ in records]
    col.add(ids=ids, documents=docs, metadatas=metas)
    return ids

def add_conversation_line(user_id: str, role: str, text: str, path: str = "./chroma_db") -> Optional[str]:
    """Add a single conversation line as a JSON record (role, text, ts). Returns the new id or None."""
    rec = {"role": role, "text": text, "ts": int(time.time())}
    ids = add_conversation_records([rec], user_id=user_id, path=path)
    return ids[0] if ids else None

def list_conversations(user_id: str, path: str = "./chroma_db") -> List[Dict[str, Any]]:
    """Return conversation records for a user as parsed JSON objects."""
    client = get_client(path)
    try:
        col = client.get_collection("conversations")
    except Exception:
        col = client.get_or_create_collection("conversations")

    try:
        data = col.get(where={"user_id": user_id})
    except Exception:
        # Fallback: get all and filter
        data = col.get()

    docs = data.get("documents", []) or []
    results: List[Dict[str, Any]] = []
    for d in docs:
        try:
            obj = json.loads(d) if isinstance(d, str) else d
        except Exception:
            # if document is plain text, try to parse basic role prefix
            obj = {"role": "unknown", "text": str(d), "ts": None}
        # ensure user_id present from metadata is consistent
        results.append(obj)

    # sort by ts if available
    try:
        results.sort(key=lambda x: x.get("ts") or 0)
    except Exception:
        pass

    return results

def delete_user(user_id: str, path: str = "./chroma_db") -> str:
    """Delete all data (memories and user info) by a given user_id."""
    client = get_client(path)
    col = client.get_or_create_collection("user_info")
    try:
        col.delete(ids=[user_id])
    except Exception as e:
        return f"Error deleting user info for {user_id}: {e}"

    delete_memories_for_user(user_id, path)
    return f"Deleted user {user_id} from db"

def delete_memories_for_user(user_id: str, path: str = "./chroma_db") -> str:
    """Delete all memories by a given user_id."""
    client = get_client(path)
    col = client.get_or_create_collection("memories")
    try:
        col.delete(where={"user_id": user_id})
        return f"Deleted memories for {user_id}"
    except Exception as e:
        return f"Error deleting memories for user {user_id}: {e}"

def list_users_with_memories(path: str = "./chroma_db") -> List[Dict[str, Any]]:
    """Return a list of users with their description and a list of their memories.

    Output structure: [{"user_id": ..., "description": ..., "memories": [...]}]
    """
    client = get_client(path)
    try:
        user_col = client.get_collection("user_info")
    except Exception:
        user_col = client.get_or_create_collection("user_info")

    try:
        mem_col = client.get_collection("memories")
    except Exception:
        mem_col = client.get_or_create_collection("memories")

    # Get all users
    users_data = user_col.get()
    user_ids = users_data.get("ids", [])
    user_docs = users_data.get("documents", [])
    user_metas = users_data.get("metadatas", [])

    # Get all memories and map them by user_id from metadata
    all_mems = mem_col.get()
    mem_docs = all_mems.get("documents", [])
    mem_metas = all_mems.get("metadatas", [])

    mems_by_user: Dict[str, List[str]] = {}
    for i, meta in enumerate(mem_metas or []):
        uid = None
        if isinstance(meta, dict):
            uid = meta.get("user_id")
        else:
            # try string parse
            try:
                d = json.loads(meta)
                uid = d.get("user_id")
            except Exception:
                uid = None

        if not uid:
            continue
        mem_text = mem_docs[i] if i < len(mem_docs) else ""
        mems_by_user.setdefault(uid, []).append(mem_text)

    # Build result list
    results: List[Dict[str, Any]] = []
    for idx, uid in enumerate(user_ids):
        desc = user_docs[idx] if idx < len(user_docs) else ""
        results.append({
            "user_id": uid,
            "description": desc,
            "memories": mems_by_user.get(uid, []),
        })

    return results

def main() -> None:
    while True:
        try:
            choice = input(
                "\nChromaDB Data Manager\n"
                "1) Create new memory\n"
                "2) Delete all memories for a user\n"
                "3) Create new user\n"
                "4) Delete a user\n"
                "5) List users with descriptions and memories\n"
                "6) Show current user\n"
                "7) Show conversation\n"
                "Choose (or 'exit' to quit): "
            )

            if not choice:
                continue
            if choice.lower() == "exit":
                break

            if choice == "1":
                text = input("Memory text: ")
                uid = input("User id (default: default_user): ") or "default_user"
                ids = add_memories([text], user_id=uid)
                conn = init_db()
                add_message(conn, uid, "user", text)
                print("Added memory ids:", ids)
            elif choice == "2":
                uid = input("User id: ")
                print(delete_memories_for_user(uid))
            elif choice == "3":
                uid = input("User id: ")
                info = input("User info text: ")
                print(add_user_info(uid, info))
            elif choice == "4":
                uid = input("User id: ")
                print(delete_user(uid))
            elif choice == "5":
                try:
                    users = list_users_with_memories()
                    for u in users:
                        print("-" * 40)
                        print(f"User ID: {u['user_id']}")
                        print(f"Description: {u.get('description','')}")
                        print("Memories:")
                        for mem in u.get('memories', []):
                            print(f"  - {mem}")
                    print("-" * 40)
                except Exception as e:
                    print(f"Failed to list users: {e}")
            elif choice == "6":
                # Local agent identity helper
                uid = get_or_create_user_id()
                print(f"Local agent user id: {uid}")
            elif choice == "7":
                print(list_conversations(get_or_create_user_id()))
            else:
                print("No action")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Error: {e}")
            continue

if __name__ == "__main__":
    main()