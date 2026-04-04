import json
import sqlite3

from agent_memory import AgentMemoryManager


def test_schema_migration_adds_and_backfills_canonical_pair(tmp_path):
    db_path = tmp_path / "agent_memory.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE conversation_logs("
        "id TEXT PRIMARY KEY, participants TEXT, log_string TEXT, place TEXT, createdOn TEXT, ts INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversation_logs(id, participants, log_string, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
        (
            "log-1",
            json.dumps(["Samson", "Jimmy"]),
            'Samson: "A"; Jimmy: "B"',
            "Workshop",
            "2026-03-15T12:00:00",
            100,
        ),
    )
    conn.commit()
    conn.close()

    manager = AgentMemoryManager(db_path=str(db_path))

    columns = {
        row[1]
        for row in manager.conn.execute("PRAGMA table_info(conversation_logs)").fetchall()
    }
    assert "canonical_pair" in columns

    canonical = manager.conn.execute(
        "SELECT canonical_pair FROM conversation_logs WHERE id='log-1'"
    ).fetchone()[0]
    assert canonical == "Jimmy&Samson"



def test_get_recent_conversation_logs_between_is_pair_exact(tmp_path):
    db_path = tmp_path / "agent_memory.db"
    manager = AgentMemoryManager(db_path=str(db_path))

    manager.add_conversation_log(
        ["Samson", "Jimmy"],
        'Samson: "Need help?"; Jimmy: "Yes"',
        "Workshop",
    )
    manager.add_conversation_log(
        ["Jimmy", "Lily"],
        'Jimmy: "Hi Lily"; Lily: "Hi"',
        "Garden",
    )

    rows = manager.get_recent_conversation_logs_between("Samson", "Jimmy", limit=5)
    assert len(rows) == 1
    assert "Need help?" in rows[0][2]
    assert "Hi Lily" not in rows[0][2]
