import os
import requests
import uuid
import chromadb
import asyncio
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

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

# Initialize ChromaDB with optimizations
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# Use cached collections to avoid repeated initialization
@lru_cache(maxsize=2)
def get_collection(name: str):
    """Cached collection getter to avoid repeated initialization"""
    return chroma_client.get_or_create_collection(name)

def get_user_collection():
    return get_collection("user_info")

def get_memories_collection():
    return get_collection("memories")

# Thread pool for concurrent operations
executor = ThreadPoolExecutor(max_workers=4)

# Cache for recent memory searches
memory_cache = {}
CACHE_DURATION = 300  # 5 minutes

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
        # Save to ChromaDB using cached collection
        get_user_collection().upsert(
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
        # Get from ChromaDB using cached collection
        results = get_user_collection().get(ids=[user_id])
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
        get_memories_collection().add(
            ids=[memory_id],
            documents=[memory],
            metadatas=[{"type": "memory", "user_id": user_id}]
        )
        # Clear cache when new memory is added
        memory_cache.clear()
        return f"Memory saved with ID: {memory_id}"
    except Exception as e:
        return f"Error saving memory: {str(e)}"

@tool
def searchMemory(query: str, config: RunnableConfig) -> str:
    """Search through stored memories using the query."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        results = get_memories_collection().query(
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

def get_cached_memory_context(query: str, user_id: str) -> str:
    """Get memory context with caching to avoid repeated database queries"""
    cache_key = f"{user_id}:{hash(query)}"
    current_time = time.time()
    
    # Check cache first
    if cache_key in memory_cache:
        cached_data, timestamp = memory_cache[cache_key]
        if current_time - timestamp < CACHE_DURATION:
            return cached_data
    
    # Query database if not in cache or expired
    try:
        results = get_memories_collection().query(
            query_texts=[query],
            n_results=3,
            where={"user_id": user_id}
        )
        if results["documents"] and len(results["documents"][0]) > 0:
            memories = results["documents"][0]
            memory_context = f"\nRelevant memories: {memories}"
        else:
            memory_context = ""
        
        # Cache the result
        memory_cache[cache_key] = (memory_context, current_time)
        return memory_context
    except:
        return ""

def duckduckgo(query: str) -> str:
    """Fast DuckDuckGo search with reduced timeout"""
    try:
        response = requests.get("https://api.duckduckgo.com/", params={
            "q": query,
            "format": "json",
            "no_redirect": 1,
            "no_html": 1
        }, timeout=5)  # Reduced timeout from 10 to 5 seconds
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
    except Exception as e:
        return f"Search error: {str(e)}"

def wikipedia_search_optimized(query: str) -> str:
    """Optimized Wikipedia search with better error handling and faster timeouts"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Single request approach - get summary directly
        response = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(" ", "_"), 
            headers=headers, timeout=8)
        
        if response.status_code == 200:
            data = response.json()
            if 'extract' in data:
                summary = data['extract'][:800] + "..." if len(data['extract']) > 800 else data['extract']
                return f"Wikipedia - {data.get('title', query)}:\n\n{summary}"
        
        # Fallback to API search if direct summary fails
        search_response = requests.get("https://en.wikipedia.org/w/api.php", 
            params={
                "action": "query", "format": "json", "list": "search", 
                "srsearch": query, "srlimit": 1
            }, 
            headers=headers, timeout=8
        )
        
        if search_response.status_code == 200:
            search_data = search_response.json()
            pages = search_data.get("query", {}).get("search", [])
            
            if pages:
                page_title = pages[0]["title"]
                # Get summary using REST API
                summary_response = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title.replace(' ', '_')}", 
                    headers=headers, timeout=8)
                
                if summary_response.status_code == 200:
                    summary_data = summary_response.json()
                    if 'extract' in summary_data:
                        summary = summary_data['extract'][:800] + "..." if len(summary_data['extract']) > 800 else summary_data['extract']
                        return f"Wikipedia - {page_title}:\n\n{summary}"
        
        return "No Wikipedia articles found for this query."
        
    except requests.exceptions.Timeout:
        return "Wikipedia search timed out."
    except Exception as e:
        return f"Wikipedia search error: {str(e)}"

search_tool = Tool.from_function(
    name="duckduckgo",
    description=(
        "Search the web using DuckDuckGo. "
        "Use ONLY if you cannot answer from your own knowledge or the user explicitly asks for a search. "
        "If the tool returns 'No direct result found', try to answer from your own knowledge."
    ),
    func=duckduckgo
)

tools = [search_tool, human_assistance, saveUserInfo, getUserInfo, saveMemory, searchMemory]
llm_with_tools = llm.bind_tools(tools)

# -----------------------
# OPTIMIZED CHATBOT NODE
# -----------------------
def chatbot(state: State):
    """Optimized chatbot with cached memory context"""
    user_id = "1"  # Get from config if needed
    
    # Use cached memory context for better performance
    if state["messages"]:
        last_message = state["messages"][-1].content
        memory_context = get_cached_memory_context(last_message, user_id)
    else:
        memory_context = ""
    
    # Optimized system prompt
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
    """Optimized streaming with better error handling"""
    try:
        for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}, config):
            for value in event.values():
                print("Assistant:", value["messages"][-1].content)
    except Exception as e:
        print(f"Error: {e}")
        print("Assistant: I encountered an error. Please try again.")

# Main loop with optimizations
if __name__ == "__main__":
    print("🚀 Optimized AI Assistant started!")
    print("Type 'quit', 'exit', or 'q' to stop.\n")
    
    while True:
        try:
            user_input = input("User: ")
            if user_input.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break
            stream_graph_updates(user_input)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            continue