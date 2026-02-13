
# Run the server with:
# & "C:/Users/WilliamKong/Documents/FYP/New folder/.venv/Scripts/python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from main import get_stream_graph_updates, summarize_conversation_and_store, config

app = FastAPI()


class ChatRequest(BaseModel):
    user_input: str

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat")
async def chat(req: ChatRequest):

    if isinstance(req.user_input, str) and req.user_input.strip().lower() == "quit":
        user_id = config.get("configurable", {}).get("user_id", "default_user")
        summary = await asyncio.to_thread(lambda: summarize_conversation_and_store(user_id))
        return {"summary": summary}

    reply = await asyncio.to_thread(lambda: get_stream_graph_updates(req.user_input))
    return {"reply": reply}

@app.post("/summarize")
async def summarize():
    try:
        user_id = config.get("configurable", {}).get("user_id", "default_user")
    except Exception:
        user_id = "default_user"

    summary = await asyncio.to_thread(lambda: summarize_conversation_and_store(user_id))
    return {"summary": summary}