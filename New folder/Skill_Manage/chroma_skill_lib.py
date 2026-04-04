import uuid
import sys
import os
import chromadb
from typing import Optional, Dict, Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unity_comm import UnityClient
from chroma_client import get_client

DEFAULT_DB_PATH = "./chroma_db"

def _get_skills_collection(client: chromadb.PersistentClient, name: str = "skills"):
    return client.get_or_create_collection(name)

def add_skill(name: str, description: str, code: str, meta: Optional[Dict[str, Any]] = None, path: str = DEFAULT_DB_PATH) -> str:
    client = get_client(path)
    col = _get_skills_collection(client)
    sid = name if name else str(uuid.uuid4())
    metadata = {"name": name, "code": code}
    if meta:
        metadata.update(meta)

    col.upsert(ids=[sid], documents=[description], metadatas=[metadata])
    return sid

def delete_skill(skill_name: str, path: str = DEFAULT_DB_PATH):
    """Delete a skill from the Chroma 'skills' collection by Name."""
    client = get_client(path)
    col = _get_skills_collection(client)
    col.delete(where={"name": skill_name})

def query_skill(query_text: str, n_results: int = 1, path: str = DEFAULT_DB_PATH):
    client = get_client(path)
    col = _get_skills_collection(client)
    res = col.query(query_texts=[query_text], n_results=n_results)
    return res

def execute_skill(skill_obj: dict, params: Optional[dict] = None, unity_client: Optional[UnityClient] = None) -> Any:
    if not skill_obj or "metadata" not in skill_obj:
        raise ValueError("Invalid skill object")

    meta = skill_obj["metadata"]
    code = meta.get("code")
    if code is None:
        raise ValueError("No code found for skill")

    ns: Dict[str, Any] = {}
    ns["unity"] = unity_client
    ns["params"] = params or {}

    exec(code, ns)

    if "run" in ns and callable(ns["run"]):
        return ns["run"](unity_client, params or {})
    else:
        return ns.get("result")

if __name__ == "__main__":
    def print_menu():
        print("\n--- Chroma Skill Manager ---")
        print("1. List all skills")
        print("2. Add a skill")
        print("3. Query/Search skills")
        print("4. Delete a skill")
        print("5. Exit")

    while True:
        print_menu()
        choice = input("Enter choice: ").strip()

        if choice == "1":
            try:
                client = get_client()
                col = _get_skills_collection(client)
                data = col.get()
                count = len(data['ids'])
                print(f"\nFound {count} skills:")
                for i in range(count):
                    sid = data['ids'][i]
                    meta = data['metadatas'][i] if data['metadatas'] else {}
                    name = meta.get('name', 'N/A') if meta else 'N/A'
                    desc = data['documents'][i] if data['documents'] else "No description"
                    print(f"- Name: {name} (ID: {sid}) | Desc: {desc[:50]}...")
            except Exception as e:
                print(f"Error listing skills: {e}")

        elif choice == "2":
            name = input("Enter skill name: ").strip()
            desc = input("Enter description: ").strip()
            print("Enter code: ")
            lines = []
            while True:
                line = input()
                if not line: break
                lines.append(line)
            code = "\n".join(lines)

            try:
                sid = add_skill(name, desc, code)
                print(f"Skill added with ID: {sid}")
            except Exception as e:
                print(f"Error adding skill: {e}")

        elif choice == "3":
            q = input("Enter query text: ").strip()
            try:
                res = query_skill(q)
                print("\nSearch Results:")
                if res and res['ids']:
                    ids = res['ids'][0]
                    for i, sid in enumerate(ids):
                        meta = res['metadatas'][0][i] if res['metadatas'] else {}
                        name = meta.get('name', 'N/A') if meta else 'N/A'
                        print(f"Match {i+1}: {name} (ID: {sid})")
                else:
                    print("No results found.")
            except Exception as e:
                print(f"Error querying skills: {e}")

        elif choice == "4":
            name = input("Enter skill name to delete: ").strip()
            confirm = input(f"Are you sure you want to delete '{name}'? (y/n): ")
            if confirm.lower() == 'y':
                try:
                    delete_skill(name)
                    print(f"Skill '{name}' deleted (if it existed).")
                except Exception as e:
                    print(f"Error deleting skill: {e}")

        elif choice == "5":
            print("Exiting.")
            break
        else:
            print("Invalid choice.")
