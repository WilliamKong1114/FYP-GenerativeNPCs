import os
import requests
import uuid
import chromadb
import asyncio
import time
import json
import re
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

from typing import Annotated
from dotenv import load_dotenv
from langchain.tools import Tool
from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages.ai import AIMessage
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver

from langgraph.store.memory import InMemoryStore
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import interrupt

load_dotenv()

chroma_client = chromadb.PersistentClient(path="./chroma_db")

@lru_cache(maxsize=2)
def get_collection(name: str):
    """Cached collection getter to avoid repeated initialization"""
    return chroma_client.get_or_create_collection(name)

def get_user_collection():
    return get_collection("user_info")

def get_memories_collection():
    return get_collection("memories")

def respond(self, message):
    if self.mood == "happy":
        return f"{self.name} (cheerful): 'That's wonderful! {message}'"
    elif self.mood == "annoyed":
        return f"{self.name} (annoyed): 'Let's just get this over with. {message}'"
    elif self.friendliness > 0.7:
        return f"{self.name} (friendly): 'I'm happy to help! {message}'"
    else:
        return f"{self.name}: '{message}'"

executor = ThreadPoolExecutor(max_workers=4)

memory_cache = {}
CACHE_DURATION = 300

store = InMemoryStore()
memory = InMemorySaver()

llm = ChatVertexAI(
    model="gemini-2.5-flash",
    temperature=0,
    max_tokens=None,
    max_retries=6,
    stop=None,
)

class Agent:
    def __init__(self, name, friendliness):
        self.name = name
        self.friendliness = friendliness
        self.mood_score = 0.0

    def update_mood(self, event):
        print(f"[Agent] current_mood(before): {self.mood_score}")
        if event == "user_rude":
            self.mood_score = max(self.mood_score - 0.5, -1.0)
        elif event == "user_nice":
            self.mood_score = min(self.mood_score + 0.5, 1.0)
        else:
            if self.mood_score > 0.0:
                self.mood_score = max(self.mood_score - 0.1, 0.0)
            elif self.mood_score < 0.0:
                self.mood_score = min(self.mood_score + 0.1, 0.0)
        print(f"[Agent] current_mood(after): {self.mood_score}")

    def get_mood_label(self):
        if self.mood_score >= 0.5:
            return "happy"
        elif self.mood_score <= -0.5:
            return "annoyed"
        else:
            return "neutral"

    def get_personality_prompt(self):
        mood_desc = {
            "happy": "You are cheerful and enthusiastic; use upbeat, encouraging language.",
            "annoyed": "You are a bit impatient; keep replies concise and direct, avoid sarcasm.",
            "neutral": "You are calm and balanced; be clear, helpful, and polite.",
        }
        if self.friendliness > 0.7:
            base_style = "You are very friendly, warm, and supportive in your responses."
        elif self.friendliness > 0.4:
            base_style = "You are moderately friendly and professional."
        else:
            base_style = "You are reserved and matter-of-fact; minimize small talk."

        return f"{mood_desc.get(self.get_mood_label(), 'Maintain a balanced tone.')} {base_style}"

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
        }, timeout=5)
        data = response.json()
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

def detect_user_sentiment(message: str) -> str:

    msg = message.lower()
    rude_words = ["stupid", "dumb", "useless", "shut up", "idiot", "don't like"]
    if any(word in msg for word in rude_words):
        return "user_rude"
    
    nice_words = ["thank", "thanks", "appreciate", "great", "awesome", "please"]
    if any(word in msg for word in nice_words):
        return "user_nice"

def chatbot(state: State):
    user_id = "1"
    
    if state["messages"]:
        last_message = state["messages"][-1].content
        memory_context = get_cached_memory_context(last_message, user_id)
        
        sentiment = detect_user_sentiment(last_message)
        agent.update_mood(sentiment)
    
    else:
        memory_context = ""
    
    system_prompt = (
        f"You are {agent.name}, a helpful assistant with access to long-term memory. "
        f"{agent.get_personality_prompt()}"
        f"If the user asks about your mood, describe your current mood in one simple sentence"
        "Answer from your own knowledge for common questions. "
        "Use memory tools to remember and recall information about users. "
        "Only use search tools if you cannot answer or the user asks for a search."
        + memory_context
    )
    # Convert any langgraph Message objects (or dicts) into plain dicts
    user_msgs = []
    for m in state.get("messages", []) or []:
        # try dict-style first, then object attributes
        if isinstance(m, dict):
            role = m.get("role") or m.get("type") or "user"
            content = m.get("content")
        else:
            role = getattr(m, "role", None) or getattr(m, "type", None) or "user"
            content = getattr(m, "content", None)

        # only include non-empty string content
        if isinstance(content, str) and content.strip():
            # Normalize role names to ones accepted by chat models
            normalized_role = str(role).lower()
            if normalized_role in ("human", "human_user", "human_user"):
                normalized_role = "user"
            if normalized_role not in ("system", "user", "assistant"):
                # default to user for any unknown role labels
                normalized_role = "user"

            user_msgs.append({"role": normalized_role, "content": content.strip()})

    # Always include the system prompt first
    msgs = [{"role": "system", "content": system_prompt}] + user_msgs

    # Defensive: ensure at least one non-empty part is sent to Vertex
    if not any(m.get("content") for m in msgs):
        # Add a minimal fallback user prompt so the request includes a parts field
        msgs.append({"role": "user", "content": "Hello."})

    # Debug logging of outgoing prompt parts to help diagnose future errors
    #print("[DEBUG] Sending prompt parts to LLM:", msgs)

    # Build a mapping of tool names to local callables for structured function calls
    tools_map = {
        "duckduckgo": duckduckgo,
        "human_assistance": human_assistance,
        "saveUserInfo": saveUserInfo,
        "getUserInfo": getUserInfo,
        "saveMemory": saveMemory,
        "searchMemory": searchMemory,
    }

    # Use the structured-call helper which expects the model to return JSON when it wants to call a tool
    response = _call_llm_with_tools_support(msgs, tools_map)

    #try:
        #print("[DEBUG] Final LLM response type:", type(response), "repr:", repr(response))
    #except Exception:
        #pass

    return {"messages": [response]}

def _call_llm_with_tools_support(msgs, tools_map, max_rounds: int = 2):
    """Call the LLM and handle structured tool calls expressed as JSON.

    Protocol (simple):
    - The model will return plain text answer or a JSON object indicating a tool call:
      {"tool": "tool_name", "args": { ... }}
    - If a tool call is returned, this function will run the mapped Python function and
      send the tool output back to the model in a follow-up call so the model can
      produce a final answer.
    """
    round = 0
    current_msgs = list(msgs)
    while round < max_rounds:
        #print("[DEBUG] _call_llm_with_tools_support: invoking LLM, round", round + 1)
        resp = llm.invoke(current_msgs)
        content = ""
        try:
            content = getattr(resp, "content", "") if resp is not None else ""
        except Exception:
            content = str(resp)

        # Try to extract JSON tool call if present
        json_obj = None
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json_obj = json.loads(stripped)
            except Exception:
                json_obj = None
        else:
            # Search for a JSON object inside the text
            m = re.search(r"(\{[\s\S]*\})", content)
            if m:
                try:
                    json_obj = json.loads(m.group(1))
                except Exception:
                    json_obj = None

        if not json_obj:
            # No tool call requested; return this response
            return resp

        # If JSON tool call found, extract tool and args
        tool_name = json_obj.get("tool")
        args = json_obj.get("args") or {}
        print(f"[INFO] Model requested tool '{tool_name}' with args: {args}")

        # Execute mapped tool if available
        tool_func = tools_map.get(tool_name)
        tool_output = None
        if tool_func:
            try:
                # support single 'query' arg common for search tools
                if isinstance(args, dict) and "query" in args and callable(tool_func):
                    tool_output = tool_func(args.get("query"))
                elif isinstance(args, dict) and len(args) == 1 and callable(tool_func):
                    # pass the only value
                    tool_output = tool_func(list(args.values())[0])
                elif callable(tool_func):
                    tool_output = tool_func(**args) if isinstance(args, dict) else tool_func(args)
                else:
                    tool_output = str(tool_func)
            except Exception as e:
                tool_output = f"Tool execution error: {e}"
        else:
            tool_output = f"Unknown tool requested: {tool_name}"

        # Append the tool result into the conversation and continue the loop
        # We add as a system message so the model can incorporate it before replying
        current_msgs.append({"role": "system", "content": f"Tool '{tool_name}' returned: {tool_output}"})
        round += 1

    # After exhausting rounds, return the last response if any
    return resp


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

agent = Agent(name="Micky", friendliness=0.8)

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