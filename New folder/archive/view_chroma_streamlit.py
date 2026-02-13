import streamlit as st
import chromadb
import pandas as pd
from typing import List

#Copy and paste the following command in your terminal to run the Streamlit app:
# & "C:/Users/WilliamKong/Documents/FYP/New folder/.venv/Scripts/python.exe" -m streamlit run "c:/Users/WilliamKong/Documents/FYP/New folder/view_chroma_streamlit.py"

@st.cache_resource
def get_client(path: str = "./chroma_db") -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=path)


def list_collections(client) -> List[str]:
    try:
        cols = client.list_collections()
        return [c.name for c in cols]
    except Exception:
        # older clients may expose a different interface
        try:
            return [c.id for c in client.list_collections()]
        except Exception:
            return []


def fetch_collection_data(collection, limit: int = 100):
    # Support older/newer chroma client get signatures
    try:
        # Note: some Chroma client versions do NOT accept 'ids' in the `include` list and will raise
        # ValueError: Expected include item to be one of documents, embeddings, metadatas, distances, uris, data, got ids
        # So don't request 'ids' via include; retrieve allowed items and fall back to any provided ids key.
        res = collection.get(include=["documents", "metadatas", "embeddings"], limit=limit)
    except TypeError:
        # fallback
        res = collection.get()
    # Some client versions return 'ids' at the top-level even if not requested; use .get() safely
    ids = res.get("ids", [])
    docs = res.get("documents", [])
    metas = res.get("metadatas", [])
    return ids, docs, metas


def main():
    st.set_page_config(page_title="Chroma DB Explorer", layout="wide")
    st.title("Chroma DB Explorer")

    db_path = st.text_input("Chroma DB Path", value="./chroma_db")
    client = get_client(db_path)

    cols = list_collections(client)
    if not cols:
        st.warning("No collections found in the Chroma DB path. Make sure the path is correct and Chroma uses PersistentClient there.")
        st.stop()

    col_name = st.selectbox("Collection", cols)
    try:
        collection = client.get_collection(col_name)
    except Exception as e:
        st.error(f"Failed to open collection '{col_name}': {e}")
        st.stop()

    st.sidebar.header("Actions")
    if st.sidebar.button("Count documents"):
        try:
            cnt = collection.count()
            st.sidebar.write("Count:", cnt)
        except Exception:
            # fallback: len of ids
            ids = collection.get(ids=None).get("ids", [])
            st.sidebar.write("Count (fallback):", len(ids))

    st.header(f"Documents in '{col_name}'")
    ids, docs, metas = fetch_collection_data(collection, limit=500)
    df = pd.DataFrame({
        "id": ids,
        "document": docs,
        "metadata": [str(m) for m in metas]
    })
    st.dataframe(df)

    st.header("Semantic Query")
    query = st.text_input("Query text")
    k = st.slider("Top-k", 1, 20, 5)
    if st.button("Search"):
        try:
            qres = collection.query(query_texts=[query], n_results=k)
            q_docs = qres.get("documents", [[]])[0]
            q_ids = qres.get("ids", [[]])[0]
            q_metas = qres.get("metadatas", [[]])[0]
            out = pd.DataFrame({"id": q_ids, "document": q_docs, "metadata": [str(m) for m in q_metas]})
            st.subheader("Results")
            st.dataframe(out)
        except Exception as e:
            st.error(f"Query failed: {e}")


if __name__ == "__main__":
    main()
