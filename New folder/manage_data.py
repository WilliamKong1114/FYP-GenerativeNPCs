from __future__ import annotations

import uuid
import json
import datetime
from typing import List, Dict, Any
from agent_memory import AgentMemoryManager
from chroma_client import get_client

memory_manager = AgentMemoryManager()

def add_user_info(user_id: str, info: str, path: str = "./chroma_db") -> str:
    client = get_client(path)
    col = client.get_or_create_collection("user_info")
    col.upsert(ids=[user_id], documents=[info], metadatas=[{"type": "user_info", "user_id": user_id, "created_at": datetime.datetime.utcnow().isoformat()}])
    return f"Created user info for {user_id}"

def add_memories(docs: List[str], user_id: str = "default_user", path: str = "./chroma_db", importance: int = 5, game_hour: float = 0) -> List[str]:
    client = get_client(path)
    col = client.get_or_create_collection("memories")
    if not docs:
        return []

    ids = [str(uuid.uuid4()) for _ in docs]
    metas = [{
        "type": "memory", 
        "user_id": user_id,
        "importance": importance,
        "created_at": game_hour,
        "modified_on": game_hour
    } for _ in docs]
    col.add(ids=ids, documents=docs, metadatas=metas)
    return ids

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
    col = client.get_collection("memories")
    try:
        col.delete(where={"user_id": user_id})
        return f"Deleted memories for {user_id}"
    except Exception as e:
        return f"Error deleting memories for user {user_id}: {e}"

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
    client = get_client(path)
    user_col = client.get_or_create_collection("user_info")
    mem_col = client.get_or_create_collection("memories")

    users_data = user_col.get()
    user_ids = users_data.get("ids", [])
    user_docs = users_data.get("documents", [])
    user_metas = users_data.get("metadatas", [])

    all_mems = mem_col.get()
    mem_docs = all_mems.get("documents", [])
    mem_metas = all_mems.get("metadatas", [])

    mems_by_user: Dict[str, List[str]] = {}
    for i, meta in enumerate(mem_metas or []):
        uid = None
        if isinstance(meta, dict):
            uid = meta.get("user_id")
        else:
            d = json.loads(meta)
            uid = d.get("user_id")

        if not uid:
            continue
        mem_text = mem_docs[i] if i < len(mem_docs) else ""
        mems_by_user.setdefault(uid, []).append(mem_text)

    results: List[Dict[str, Any]] = []
    for idx, uid in enumerate(user_ids):
        desc = user_docs[idx] if idx < len(user_docs) else ""
        results.append({
            "user_id": uid,
            "description": desc,
            "memories": mems_by_user.get(uid, []),
        })

    return results

def list_users(path: str = "./chroma_db") -> List[Dict[str, Any]]:
    client = get_client(path)
    user_col = client.get_or_create_collection("user_info")

    users_data = user_col.get()
    user_ids = users_data.get("ids", [])
    user_docs = users_data.get("documents", [])

    results: List[Dict[str, Any]] = []
    for idx, uid in enumerate(user_ids):
        desc = user_docs[idx]
        results.append({
            "user_id": uid,
            "description": desc
        })

    return results

def main() -> None:
    menu_options = {
        "1": {
            "description": "Create new memory for a user",
            "function": lambda: add_memories([input("Memory text: ")], user_id=input("User id (default: default_user): ") or "default_user"),
            "print_result": lambda ids: print("Added memory ids:", ids),
        },
        "2": {
            "description": "Clear memories for a user",
            "function": lambda: delete_memories_for_user(input("User id: ")),
            "print_result": lambda result: print(result),
        },
        "3": {
            "description": "Create new user",
            "function": lambda: add_user_info(input("User id: "), input("User info text: ")),
            "print_result": lambda result: print(result),
        },
        "4": {
            "description": "Delete a user",
            "function": lambda: delete_user(input("User id: ")),
            "print_result": lambda result: print(result),
        },
        "5": {
            "description": "List users with descriptions and memories",
            "function": lambda: list_users_with_memories(),
            "print_result": lambda users: (
                [print("-" * 40, f"User ID: {u['user_id']}", f"Description: {u.get('description', '')}", "Memories:", *[f"  - {mem}" for mem in u.get('memories', [])], "-" * 40, sep="\n") for u in users]
            ),
        },
        "6": {
            "description": "List users",
            "function": lambda: list_users(),
            "print_result": lambda users: print("Users in DB: " + ", ".join([u['user_id'] for u in users]) if users else "No users found.")
        },
        "7": {
            "description": "Set active user",
            "function": lambda: (memory_manager.__setattr__('user_id', (new_uid := input("Enter new user ID to activate: ").strip()) or None), new_uid)[1],
            "print_result": lambda new_uid: print(f"Active user set to: {new_uid}" if new_uid else "No user ID entered."),
        },
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