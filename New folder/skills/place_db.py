import sqlite3
import json
import uuid
from typing import Optional, Dict, Any, List

DB_PATH = "./places.db"

def _get_conn(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS places (
        uuid TEXT PRIMARY KEY UNIQUE,
        name TEXT NOT NULL,
        position TEXT, -- JSON: [x, y]
        metadata TEXT
    )""")
    conn.commit()
    return conn

def add_place(name: str, position, metadata: Optional[Dict[str, Any]] = None, path: str = DB_PATH) -> None:
    pos_parts = [p.strip() for p in position.split(",")]  
    pos_text = f"{float(pos_parts[0])},{float(pos_parts[1])}"
    meta = json.dumps(metadata or {})

    conn = _get_conn(path)
    uid = str(uuid.uuid4())
    conn.execute("INSERT OR REPLACE INTO places (uuid, name, position, metadata) VALUES (?, ?, ?, ?)", (uid, name, pos_text, meta))
    conn.commit()
    conn.close()

def get_place(name: str, path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(path)
    cur = conn.execute("SELECT uuid, name, position, metadata FROM places WHERE name = ?", (name, ))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None
    uid, pname, pos_text, meta_text = row
    position = pos_text if pos_text else None
    meta = json.loads(meta_text) if meta_text else {}

    return {"uuid": uid, "name": pname, "position": position, "metadata": meta}

def list_places(path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = _get_conn(path)
    cur = conn.execute("SELECT uuid, name, position, metadata FROM places ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    result = []
    for uid, name, pos_text, meta_text in rows:
        position = pos_text if pos_text else None
        meta = json.loads(meta_text) if meta_text else {None}
        result.append({"uuid": uid, "name": name, "position": position, "metadata": meta})
    return result

def delete_place(name: str, path: str = DB_PATH) -> None:
    conn = _get_conn(path)
    conn.execute("DELETE FROM places WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def main() -> None:
    while True:
        try:
            choice = input(
                "\nPlace Manager\n"
                "1) List places\n"
                "2) Add place\n"
                "3) Get place\n"
                "4) Delete place\n"
                "Choose (or 'exit' to quit): "
            )

            if not choice:
                continue
            if choice.lower() == "exit":
                break

            if choice == "1":
                places = list_places()
                if not places:
                    print("No places found.")
                for p in places:
                    print(f"- {p['name']}: {p['position']}; {p['metadata']}")

            elif choice == "2":
                name = input("Place name: ").strip()
                if not name:
                    print("Name required")
                    continue
                position = input("Position (x, y): ").strip()
                #meta_in = input("Metadata as JSON (or leave blank): ").strip()
                pos_obj = position if position else None
                #meta_obj = json.loads(meta_in) if meta_in else None
                add_place(name, pos_obj)
                print("Added/updated place:", name)

            elif choice == "3":
                name = input("Place name: ").strip()
                if not name:
                    print("Name required")
                    continue
                v = get_place(name)
                if v is None:
                    print("Place not found")
                else:
                    print(json.dumps(v, indent=2))

            elif choice == "4":
                name = input("Place name: ").strip()
                if not name:
                    print("Name required")
                    continue
                delete_place(name)
                print("Deleted:", name)
            else:
                print("Unknown option")

        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print("Error:", e)
            continue

if __name__ == "__main__":
    main()