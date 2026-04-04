import json
from typing import List, Dict, Any
from Skill_Manage.chroma_skill_lib import add_skill as add_skill_lib, delete_skill as delete_skill_lib
from chroma_client import get_client

def list_skills(chroma_path: str = "./chroma_db") -> List[Dict[str, Any]]:
    client = get_client(chroma_path)
    try:
        col = client.get_collection("skills")
    except Exception:
        col = client.get_or_create_collection("skills")
    data = col.get()
    ids = data.get("ids", []) or []
    docs = data.get("documents", []) or []
    metas = data.get("metadatas", []) or []

    # normalize
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    if docs and isinstance(docs[0], list):
        docs = docs[0]
    if metas and isinstance(metas[0], list):
        metas = metas[0]

    items = []
    for i, sid in enumerate(ids):
        items.append({"id": sid, "doc": docs[i] if i < len(docs) else None, "meta": metas[i] if i < len(metas) else None})
    return items

def show_skill(sid: str, chroma_path: str = "./chroma_db") -> Dict[str, Any]:
    items = list_skills(chroma_path)
    for it in items:
        if it.get("id") == sid:
            return it
    raise KeyError(f"Skill id not found: {sid}")

def _cli():
    import argparse

    p = argparse.ArgumentParser(description="Inspect Chroma skills collection")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list-skills")
    
    s = sub.add_parser("show-skill")
    s.add_argument("id")
    
    d = sub.add_parser("delete-skill")
    d.add_argument("id")

    args = p.parse_args()

    if args.cmd == "list-skills":
        for it in list_skills():
            print(it["id"], "-", (it["doc"] or ""))
    elif args.cmd == "show-skill":
        try:
            it = show_skill(args.id)
            print(json.dumps(it, indent=2))
        except KeyError as e:
            print(str(e))
    elif args.cmd == "delete-skill":
        delete_skill_lib(args.id)
        print(f"Deleted skill {args.id}")
    else:
        p.print_help()

if __name__ == "__main__":
    _cli()
