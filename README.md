# Dynamic Interactive System with AI-driven NPCs

Short project README for local setup and quick reference.

## Description

This repository contains an experimental system that composes an AI-driven conversational graph for NPCs (non-player characters) using ChromaDB for memory storage and Google Vertex AI (via `langchain-google-vertexai`) as the LLM backend. The project includes:

- A graph-based chatbot engine (`main.py`) which manages tools, memories, and streaming responses.
- A small FastAPI wrapper (`api.py`) exposing a `/chat` endpoint for programmatic access.
- A Streamlit utility (`view_chroma_streamlit.py`) for inspecting ChromaDB collections.
- A `performance_test.py` script for benchmarking search approaches.

## Quick Setup (Windows PowerShell)

1. Clone the repo and enter the folder:

```powershell
git clone <repo-url>
cd "New folder"
```

2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Add secrets locally (do NOT commit them). Example: set Google service account env var in PowerShell for the session:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\path\to\finalyearproject-xxxx.json'
```

Alternatively, copy `.env.example` to `.env` and populate the values.

## Run

- Run the interactive loop in `main.py` (simple REPL):

```powershell
python main.py
```

- Run the FastAPI server (for programmatic access):

```powershell
# from repo root
& "${env:USERPROFILE}\.venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

- Run the Streamlit DB viewer:

```powershell
& ".venv\Scripts\python.exe" -m streamlit run view_chroma_streamlit.py
```

## Environment variables (`.env`)

Create a `.env` (copy from `.env.example`) and fill real values locally. Do NOT commit this file.

## Helpful commands

```powershell
# Remove secrets from index (keeps local copy)
git rm --cached finalyearproject-473307-5f81b95b0dbf.json
git rm --cached finalyearproject-473307-a9217e681ea4.json
git commit -m "Remove service account JSON from repo and add to .gitignore"
git push
```
