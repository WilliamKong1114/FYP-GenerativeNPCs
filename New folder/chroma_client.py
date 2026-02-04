import chromadb
import chromadb.config
from pathlib import Path
from typing import Dict

_CLIENTS: Dict[str, chromadb.PersistentClient] = {}

def get_client(path: str = "./chroma_db") -> chromadb.PersistentClient:
    if path in _CLIENTS:
        return _CLIENTS[path]

    db_file = Path(path) / "chroma.sqlite3"

    if db_file.exists():
        client = chromadb.PersistentClient(path=path)
        _CLIENTS[path] = client
        return client

    try:
        client = chromadb.PersistentClient(path=path)
        client.heartbeat() # Test connection
    except Exception:
        # Fallback for very old versions or specific issues, though generic constructor should work
        settings = chromadb.config.Settings(
            allow_reset=True,
            anonymized_telemetry=False,
        )
        client = chromadb.PersistentClient(path=path, settings=settings)

    _CLIENTS[path] = client
    return client
