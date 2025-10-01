import os
import requests
import uuid
import chromadb

from typing import Annotated
from dotenv import load_dotenv
from langchain.tools import Tool
from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver

from langgraph.store.memory import InMemoryStore
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import interrupt

load_dotenv()

# Use ChromaDB for persistent memory storage
chroma_client = chromadb.PersistentClient(path="./chroma_db")
user_collection = chroma_client.get_or_create_collection("user_info")
memories_collection = chroma_client.get_or_create_collection("memories")

# Keep InMemoryStore for LangGraph compatibility
store = InMemoryStore()
memory = InMemorySaver()

llm = ChatVertexAI(
    model="gemini-2.5-flash",
    temperature=0,
    max_tokens=None,
    max_retries=6,
    stop=None,
)

class State(TypedDict):
    messages: Annotated[list, add_messages]

builder = StateGraph(State)

@tool
def human_assistance(query: str) -> str:
    """Ask a human for help with the query."""
    return interrupt({"query": query})

@tool
def saveUserInfo(info: str, config: RunnableConfig) -> str:
    """Save user information to long-term memory."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        # Save to ChromaDB
        user_collection.upsert(
            ids=[user_id],
            documents=[info],
            metadatas=[{"type": "user_info", "user_id": user_id}]
        )
        return f"Saved info for {user_id}."
    except Exception as e:
        return f"Error saving info: {str(e)}"

@tool
def getUserInfo(config: RunnableConfig) -> str:
    """Retrieve user information from long-term memory."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        # Get from ChromaDB
        results = user_collection.get(ids=[user_id])
        if results["documents"] and len(results["documents"]) > 0:
            return results["documents"][0]
        return f"No info found for {user_id}."
    except Exception as e:
        return f"Error retrieving info: {str(e)}"

@tool
def saveMemory(memory: str, config: RunnableConfig) -> str:
    """Save a memory to long-term storage."""
    user_id = config["configurable"].get("user_id", "default_user")
    memory_id = str(uuid.uuid4())
    try:
        memories_collection.add(
            ids=[memory_id],
            documents=[memory],
            metadatas=[{"type": "memory", "user_id": user_id}]
        )
        return f"Memory saved with ID: {memory_id}"
    except Exception as e:
        return f"Error saving memory: {str(e)}"

@tool
def searchMemories(query: str, config: RunnableConfig) -> str:
    """Search through stored memories using the query."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        results = memories_collection.query(
            query_texts=[query],
            n_results=3,
            where={"user_id": user_id}
        )
        if results["documents"] and len(results["documents"][0]) > 0:
            memories = results["documents"][0]
            return f"Found {len(memories)} memories: {memories}"
        return "No memories found."
    except Exception as e:
        return f"Error searching memories: {str(e)}"
    
def duckduckgo(query: str) -> str:
    response = requests.get("https://api.duckduckgo.com/", params={
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1
    }, timeout=10)
    data = response.json()
    # Try multiple fields for better coverage
    for key in ["AbstractText", "Abstract", "Heading"]:
        if data.get(key):
            return data[key]
    related = data.get("RelatedTopics") or []
    for item in related:
        if isinstance(item, dict) and item.get("Text"):
            return item["Text"]
    return "No direct result found."

search_tool = Tool.from_function(
    name="custom_search",
    description=(
        "Search the web using DuckDuckGo. "
        "Use ONLY if you cannot answer from your own knowledge or the user explicitly asks for a search. "
        "If the tool returns 'No direct result found', try to answer from your own knowledge."
    ),
    func=duckduckgo
)

tools = [search_tool, human_assistance, saveUserInfo, getUserInfo, saveMemory, searchMemories]
llm_with_tools = llm.bind_tools(tools)

# -----------------------
# CHATBOT NODE
# -----------------------
def chatbot(state: State):
    # Search for relevant memories based on the last user message
    memory_context = ""
    if state["messages"]:
        last_message = state["messages"][-1].content
        try:
            # Search memories using ChromaDB
            results = memories_collection.query(
                query_texts=[last_message],
                n_results=3,
                where={"user_id": "1"}
            )
            if results["documents"] and len(results["documents"][0]) > 0:
                memories = results["documents"][0]
                memory_context = f"\nRelevant memories: {memories}"
        except:
            memory_context = ""
    
    # Add a system prompt to guide tool usage
    system_prompt = (
        "You are a helpful assistant with access to long-term memory. "
        "Answer from your own knowledge for common questions. "
        "Use memory tools to remember and recall information about users. "
        "Only use search tools if you cannot answer or the user asks for a search."
        + memory_context
    )
    msgs = [{"role": "system", "content": system_prompt}, *state["messages"]]
    return {"messages": [llm_with_tools.invoke(msgs)]}

builder.add_node("chatbot", chatbot)

tool_node = ToolNode(tools=tools)
builder.add_node("tools", tool_node)
builder.add_conditional_edges("chatbot", tools_condition)
builder.add_edge("tools", "chatbot")

builder.set_entry_point("chatbot")
builder.add_edge("chatbot", END)

memory = InMemorySaver()
graph = builder.compile(checkpointer=memory, store=store)

config = {"configurable": {"thread_id": "1", "user_id": "1"}}

def stream_graph_updates(user_input: str):
    for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}, config):
        for value in event.values():
            print("Assistant:", value["messages"][-1].content)

while True:
    try:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break
        stream_graph_updates(user_input)
    except:
        break
