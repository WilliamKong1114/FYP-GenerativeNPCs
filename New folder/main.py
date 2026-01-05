import os
import requests
import uuid
import asyncio
import time
import json
import re
import chromadb
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

from typing import Annotated, Optional
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

import manage_data

load_dotenv()

chroma_client = chromadb.PersistentClient(path="./chroma_db")

@lru_cache(maxsize=2)
def get_collection(name: str):
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
            base_style = "You are in an average normal mood."
        else:
            base_style = "You minimize small talk. Trying to be as brief as possible."

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

tools = [human_assistance, saveUserInfo, getUserInfo, saveMemory, searchMemory]
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
    user_id = config.get("configurable", {}).get("user_id", "1")
    
    if state["messages"]:
        last_message = state["messages"][-1].content
        memory_context = get_cached_memory_context(last_message, user_id)
        
        sentiment = detect_user_sentiment(last_message)
        agent.update_mood(sentiment)
    else:
        memory_context = ""

    system_prompt = f"""
        You are {agent.name}, a villager.
        You live in a quiet wooden-house village on flat land, 
        surrounded by forests and rivers under calm, pleasant skies.
        {agent.get_personality_prompt()}
        Answer from your own knowledge for common questions.
        Use memory tools to remember and recall information about users.
        You have access to your long-term memory.
        Here is the related memory context to make the conversation more related to current situation:{memory_context}.
        Remember each detail data and information that you consider important 
        in constructing a more complete and detailed user profile about the user 
        during a conversation between user and you. Examples include but are not limited to:
        user's preferences, interests, hobbies, important life events, personal anecdotes, etc."""

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

    msgs = [{"role": "system", "content": system_prompt}] + user_msgs

    if not any(m.get("content") for m in msgs):
        # Add a minimal fallback user prompt so the request includes a parts field
        msgs.append({"role": "user", "content": "Hello."})

    tools_map = {
        "human_assistance": human_assistance,
        "saveUserInfo": saveUserInfo,
        "getUserInfo": getUserInfo,
        "saveMemory": saveMemory,
        "searchMemory": searchMemory,
    }

    response = _call_llm_with_tools_support(msgs, tools_map)
    return {"messages": [response]}

def _call_llm_with_tools_support(msgs, tools_map, max_rounds: int = 2):
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

try:
    runtime_user_id = manage_data.get_or_create_user_id()
except Exception:
    runtime_user_id = "1"

config = {"configurable": {"thread_id": "1", "user_id": runtime_user_id}}
print(f"Using user_id={config['configurable']['user_id']}")

agent = Agent(name="Micky", friendliness=0.8)

def stream_graph_updates(user_input: str):
    """Optimized streaming with better error handling"""
    try:
        # Save the incoming user line into ChromaDB (conversation JSON)
        try:
            uid = config.get("configurable", {}).get("user_id", "default_user")
            manage_data.add_conversation_line(user_id=uid, role="user", text=user_input)
        except Exception:
            pass

        # Stream and capture assistant replies, saving each line
        for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}, config):
            for value in event.values():
                reply = value["messages"][-1].content
                print(f"{agent.name}:", reply)
                try:
                    uid = config.get("configurable", {}).get("user_id", "default_user")
                    manage_data.add_conversation_line(user_id=uid, role="assistant", text=reply)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error: {e}")
        print(f"{agent.name}: I encountered an error. Please try again.")

def get_stream_graph_updates(user_input: str) -> str:
    """Get the full assistant reply as a string"""
    reply_parts = []
    try:
        # Save incoming user line into ChromaDB
        uid = config.get("configurable", {}).get("user_id", "default_user")
        manage_data.add_conversation_line(user_id=uid, role="user", text=user_input)

        # ensure we always use accepted role names
        for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}, config):
            for value in event.values():
                reply = value["messages"][-1].content
                reply_parts.append(reply)
                # Save assistant reply line into ChromaDB
                uid = config.get("configurable", {}).get("user_id", "default_user")
                manage_data.add_conversation_line(user_id=uid, role="assistant", text=reply)
    except Exception as e:
        return f"Error: {e}. I encountered an error. Please try again."
    
    return " ".join(reply_parts)

def get_conversation_records() -> list[dict[str, str]]:
    """Retrieve the conversation records from the current thread."""
    state = graph.get_state(config)
    messages = state.values.get("messages", [])
    records = []
    for msg in messages:
        if hasattr(msg, 'type') and hasattr(msg, 'content'):
            records.append({"role": msg.type, "content": msg.content})
        elif isinstance(msg, dict):
            records.append({"role": msg.get("role", "unknown"), "content": msg.get("content", "")})
    return records

def summarize_conversation_and_store(user_id: str) -> Optional[str]:
    """Fetch conversation lines for `user_id`, ask the LLM for a concise summary,
    store the summary into the `memories` collection and return it.
    """
    try:
        convs = manage_data.list_conversations(user_id)
        if not convs:
            return None

        parts = []
        for c in convs:
            role = c.get("role", "unknown")
            text = c.get("text") or c.get("content") or ""
            ts = c.get("ts")
            parts.append(f"[{role}] {text}")

        convo_text = "\n".join(parts[-35:])  # limit size a bit

        system = {
            "role": "system",
            "content": "You are a concise summarizer. Produce one short (<=35 words) informative and concise summary sentence that captures the user's profile, preferences, important facts and the main intent from the conversation."
        }
        user_msg = {"role": "user", "content": f"Summarize the following conversation into one concise informative sentence:\n\n{convo_text}"}

        resp = llm.invoke([system, user_msg])
        summary = getattr(resp, "content", None) or str(resp)

        # Store summary into semantic memories for retrieval
        manage_data.add_memories([summary], user_id=user_id)

        # Also print summary locally
        print("--- Conversation summary saved to memories ---")
        print(summary)
        return summary
    except Exception as e:
        print(f"Failed to summarize conversation: {e}")
        return None

if __name__ == "__main__":
    while True:
        try:
            user_input = input("User: ")
            if user_input.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                # Summarize the conversation and store the concise summary into memories
                summarize_conversation_and_store(config.get("configurable", {}).get("user_id", "1"))
                break
            stream_graph_updates(user_input)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            summarize_conversation_and_store(config.get("configurable", {}).get("user_id", "1"))
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            continue