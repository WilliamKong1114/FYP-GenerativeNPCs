import chromadb
import chromadb.config
from pathlib import Path
from typing import Dict

_CLIENTS: Dict[str, chromadb.PersistentClient] = {}

def get_client(path: str = "./chroma_db") -> chromadb.PersistentClient:
    if path in _CLIENTS:
        return _CLIENTS[path]

    db_path = Path(path)
    if not db_path.is_dir():
        db_path.mkdir(parents=True, exist_ok=True)

    settings = chromadb.config.Settings(
        allow_reset=True,
        anonymized_telemetry=False,
    )
    
    try:
        client = chromadb.PersistentClient(path=str(db_path), settings=settings)
        client.heartbeat()  # Always test connection
    except chromadb.errors.ChromaError as e:
        raise RuntimeError(f"Failed to create Chroma client at {path}: {e}") from e

    _CLIENTS[path] = client
    return client