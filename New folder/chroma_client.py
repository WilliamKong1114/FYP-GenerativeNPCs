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
        settings = chromadb.config.Settings(
            chroma_api_impl="chromadb.api.segment.SegmentAPI",
            chroma_sysdb_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_producer_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_consumer_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_segment_manager_impl="chromadb.segment.impl.manager.local.LocalSegmentManager",
            allow_reset=True,
            anonymized_telemetry=False,
        )
        client = chromadb.PersistentClient(path=path, settings=settings)
    except Exception:
        client = chromadb.PersistentClient(path=path)

    _CLIENTS[path] = client
    return client
