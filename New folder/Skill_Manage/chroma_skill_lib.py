import uuid
import chromadb
from typing import Optional, Dict, Any
from unity_comm import UnityClient

DEFAULT_DB_PATH = "./chroma_db"

def get_client(path: str = DEFAULT_DB_PATH) -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=path)

def get_skills_collection(client: chromadb.PersistentClient, name: str = "skills"):
    return client.get_or_create_collection(name)

def add_skill(name: str, description: str, code: str, meta: Optional[Dict[str, Any]] = None, path: str = DEFAULT_DB_PATH) -> str:
    """Add a skill to the Chroma 'skills' collection. Returns the skill id."""
    client = get_client(path)
    col = get_skills_collection(client)
    sid = name if name else str(uuid.uuid4())
    metadata = {"name": name, "code": code}
    if meta:
        metadata.update(meta)

    col.upsert(ids=[sid], documents=[description], metadatas=[metadata])
    return sid

def query_skill(query_text: str, n_results: int = 1, path: str = DEFAULT_DB_PATH):
    client = get_client(path)
    col = get_skills_collection(client)
    res = col.query(query_texts=[query_text], n_results=n_results)
    return res

def _extract_skill_from_query_result(query_result: dict, index: int = 0):
    ids = query_result.get("ids", [])
    docs = query_result.get("documents", [])
    metas = query_result.get("metadatas", [])
    if not ids or index >= len(ids[0]):
        return None
    return {
        "id": ids[0][index],
        "description": docs[0][index] if docs and len(docs[0]) > index else None,
        "metadata": metas[0][index] if metas and len(metas[0]) > index else None,
    }

def get_best_skill(query_text: str, path: str = DEFAULT_DB_PATH):
    res = query_skill(query_text, n_results=1, path=path)
    return _extract_skill_from_query_result(res, 0)

def execute_skill(skill_obj: dict, params: Optional[dict] = None, unity_client: Optional[UnityClient] = None) -> Any:
    if not skill_obj or "metadata" not in skill_obj:
        raise ValueError("Invalid skill object")

    meta = skill_obj["metadata"]
    code = meta.get("code")
    if code is None:
        raise ValueError("No code found for skill")

    # Prepare execution namespace. Provide `unity` and `params`.
    ns: Dict[str, Any] = {}
    ns["unity"] = unity_client
    ns["params"] = params or {}

    # Execute code (trusted context). Code should define `run(unity, params)`.
    exec(code, ns)

    if "run" in ns and callable(ns["run"]):
        return ns["run"](unity_client, params or {})
    else:
        # If code sets a variable `result`, return it
        return ns.get("result")
