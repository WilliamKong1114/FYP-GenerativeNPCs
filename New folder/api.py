
# Run the server with:
# & "C:/Users/WilliamKong/Documents/FYP/New folder/.venv/Scripts/python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload

from fastapi import FastAPI
from pydantic import BaseModel
import asyncio
from main import get_stream_graph_updates 
app = FastAPI()

class ChatRequest(BaseModel):
    user_input: str

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    reply = await asyncio.to_thread(lambda: get_stream_graph_updates(req.user_input))
    return {"reply": reply}