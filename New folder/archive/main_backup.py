# .\.venv\Scripts\python.exe main.py

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

import chroma_memory_manager

load_dotenv()

chroma_client = chromadb.PersistentClient(path="./chroma_db")

@lru_cache(maxsize=2)
def get_collection(name: str):
    return chroma_client.get_or_create_collection(name)

def get_user_collection():
    return get_collection("user_info")

def get_memories_collection():
    return get_collection("memories")

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
        self.mood_score = 0.5

    def update_mood(self, event):
        if event == "user_rude":
            self.mood_score = max(self.mood_score - 0.5, -1.0)
        elif event == "user_nice":
            self.mood_score = min(self.mood_score + 0.5, 1.0)
        else:
            if self.mood_score > 0.0:
                self.mood_score = max(self.mood_score - 0.1, 0.0)
            elif self.mood_score < 0.0:
                self.mood_score = min(self.mood_score + 0.1, 0.0)

    def get_mood(self):
        if self.mood_score >= 0.5:
            return "happy"
        elif self.mood_score <= -0.5:
            return "annoyed"
        else:
            return "neutral"

    def get_personality_prompt(self):
        mood_desc = {
            "happy": "You are cheerful and enthusiastic; use upbeat, encouraging language.",
            "annoyed": "You are a bit impatient; keep replies concise and direct.",
            "neutral": "You are calm and balanced.",
        }
        if self.friendliness > 0.7:
            base_style = "You are very friendly and supportive. Show genuine interest in what the user says."
        elif self.friendliness > 0.4:
            base_style = "You are in a normal, easy-going mood. Keep things casual and pleasant."
        else:
            base_style = "You prefer to keep things brief and practical, with minimal small talk."

        return f"{mood_desc.get(self.get_mood(), 'Maintain a balanced tone.')} {base_style}"

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

tools = [human_assistance, saveUserInfo, getUserInfo]
llm_with_tools = llm.bind_tools(tools)

def detect_user_sentiment(message: str) -> str:
    msg = message.lower()
    rude_words = ["stupid", "dumb", "useless", "shut up", "idiot", "don't like"]
    if any(word in msg for word in rude_words):
        return "user_rude"
    
    nice_words = ["thank", "thanks", "appreciate", "great", "awesome", "please"]
    if any(word in msg for word in nice_words):
        return "user_nice"

def agent_node(state: State, config: RunnableConfig):
    conf = config.get("configurable", {})
    user_id = conf.get("user_id", "1")
    agent_name = conf.get("agent_name", "Micky")
    agent_persona = conf.get("agent_persona", "You are a friendly assistant.")
    
    if state["messages"]:
        last_message = state["messages"][-1].content
        memory_context = get_cached_memory_context(last_message, user_id)
        # sentiment = detect_user_sentiment(last_message)
    else:
        memory_context = ""

    system_prompt = f"""
        You are {agent_name}, a villager living in a village on flat land surrounded by forests and rivers.
        {agent_persona}
        Answer common questions using your own knowledge.
        Use memory tools to remember and recall information about users. 
        Minimize greetings, salutations, or sign-offs. Start immediately with the answer.
        Access the memory context to make the conversation relevant to current situation:{memory_context}.
        
        Respond in a casual, human-like tone that feels natural. 
        - Use short sentences, contractions, and everyday language. 
        - Avoid sounding overly formal or poetic. 
        - Keep it simple and conversational, like chatting with a friend. 
        - Avoid repeating previous statements and topics unless necessary.
        - Adapt responses to the user’s latest input and keep them fresh.
        - Show curiosity and light enthusiasm naturally.
        - Determine when to ask questions to keep the conversation flowing, but avoid asking too many in a row.
        - Start no more than 3 topics within a conversation.
        - Try to end conversations if the user seems disinterested or if the topic has been exhausted.

        Example:
        If someone mentions going fishing by the river, you might say:
        "Ah, the river just down there! That’s convenient. Hope you catch some fish! Fishing is such a great way to relax, don’t you think?"
        """

    user_msgs = []
    for m in state.get("messages", []) or []:
        if isinstance(m, dict):
            role = m.get("role") or m.get("type") or "user"
            content = m.get("content")
        else:
            role = getattr(m, "role", None) or getattr(m, "type", None) or "user"
            content = getattr(m, "content", None)

        if isinstance(content, str) and content.strip():
            normalized_role = str(role).lower()
            if normalized_role in ("human", "human_user", "human_user"):
                normalized_role = "user"
            if normalized_role not in ("system", "user", "assistant"):
                normalized_role = "user"

            user_msgs.append({"role": normalized_role, "content": content.strip()})

    msgs = [{"role": "system", "content": system_prompt}] + user_msgs
    tools_map = {
        "human_assistance": human_assistance,
        "saveUserInfo": saveUserInfo,
        "getUserInfo": getUserInfo,
        #"saveMemory": saveMemory,
        #"searchMemory": searchMemory,
    }

    response = _call_llm_with_tools_support(msgs, tools_map)
    return {"messages": [response]}

def _call_llm_with_tools_support(msgs, tools_map, max_rounds: int = 2):
    round = 0
    current_msgs = list(msgs)
    while round < max_rounds:
        resp = llm.invoke(current_msgs)
        content = ""
        try:
            content = getattr(resp, "content", "") if resp is not None else ""
        except Exception:
            content = str(resp)

        json_obj = None
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json_obj = json.loads(stripped)
            except Exception:
                json_obj = None
        else:
            m = re.search(r"(\{[\s\S]*\})", content)
            if m:
                try:
                    json_obj = json.loads(m.group(1))
                except Exception:
                    json_obj = None

        if not json_obj:
            return resp

        tool_name = json_obj.get("tool")
        args = json_obj.get("args") or {}
        print(f"[INFO] Model requested tool '{tool_name}' with args: {args}")

        tool_func = tools_map.get(tool_name)
        tool_output = None
        if tool_func:
            try:
                if isinstance(args, dict) and "query" in args and callable(tool_func):
                    tool_output = tool_func(args.get("query"))
                elif isinstance(args, dict) and len(args) == 1 and callable(tool_func):
                    tool_output = tool_func(list(args.values())[0])
                elif callable(tool_func):
                    tool_output = tool_func(**args) if isinstance(args, dict) else tool_func(args)
                else:
                    tool_output = str(tool_func)
            except Exception as e:
                tool_output = f"Tool execution error: {e}"
        else:
            tool_output = f"Unknown tool requested: {tool_name}"

        current_msgs.append({"role": "system", "content": f"Tool '{tool_name}' returned: {tool_output}"})
        round += 1

    return resp

builder.add_node("agent", agent_node)

tool_node = ToolNode(tools=tools)
builder.add_node("tools", tool_node)
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")

builder.set_entry_point("agent")
builder.add_edge("agent", END)

memory = InMemorySaver()
graph = builder.compile(checkpointer=memory, store=store)

runtime_user_id = chroma_memory_manager.get_or_create_user_id()
default_agent = Agent(name=runtime_user_id, friendliness=0.8)

config = {
    "configurable": {
        "thread_id": "1", 
        "user_id": runtime_user_id,
        "agent_name": default_agent.name,
        "agent_persona": default_agent.get_personality_prompt()
    }
}

def generate_agent_response(agent_id: str, agent_persona: str, triggering_msg: str, sender_id: str, thread_id: str = None) -> str:
    #if not thread_id:
    #    thread_id = f"{agent_id}-mem"
    
    run_config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": agent_id,
            "agent_name": agent_id,
            "agent_persona": agent_persona
        }
    }
    
    inputs = {"messages": [{"role": "user", "content": triggering_msg}]}
    
    response_content = ""
    try:
        result = graph.invoke(inputs, run_config)
        messages = result.get("messages", [])
        if messages:
            response_content = messages[-1].content
    except Exception as e:
        print(f"Error generating response for {agent_id}: {e}")
        response_content = "..."

    return response_content

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

def summarize_conversation_and_store(user_id: str, raw_log: str = None, log_id: str = None) -> Optional[str]:
    try:
        memory_cache.clear()
        if raw_log:
            convo_text = raw_log
        else:
            convs = get_conversation_records()
            if not convs:
                convs = chroma_memory_manager.list_conversations(user_id)
                if not convs:
                    return None

            parts = []
            for c in convs:
                if isinstance(c, dict):
                    role = c.get("role", "unknown")
                    text = c.get("text") or c.get("content") or ""
                else:
                    role = "unknown"
                    text = str(c)
                if not text or not isinstance(text, str) or not text.strip():
                    continue
                parts.append(f"[{role}] {text.strip()}")
            
            convo_text = "\n".join(parts[-200:])

        convo_Length = 200
        system = {
            "role": "system",
            "content": 
                f"""You are a concise memory summarizer for a generative agent named {user_id}. 
                Distill the following conversation into one short, factual sentence (<={convo_Length} words) to be stored as {user_id}'s memory.
                The summary must capture:
                1. {user_id}'s own revealed plans, intent, or identity traits.
                2. Key information, news, or observations {user_id} gathered about the conversation partner.
                3. The main outcome or topic of the interaction.
                Write the summary in the third person (e.g., '{user_id} discussed ... and learned that ...'). 
                Output only the sentence — no explanations or filler."""
        }
        user_msg = {"role": "user", "content": f"Summarize the following conversation into one concise informative sentence:\n\n{convo_text}"}

        resp = llm.invoke([system, user_msg])
        summary = getattr(resp, "content", None) or str(resp)

        chroma_memory_manager.add_memories([summary], user_id=user_id)
        chroma_memory_manager.save_user_summary(user_id, summary, log_id=log_id)

        print(f"--- Conversation summary for {user_id} saved ---")
        print(summary)
        return summary
    except Exception as e:
        print(f"Failed to summarize conversation for {user_id}: {e}")
        return None

#if __name__ == "__main__":
#    while True:
#        try:
#            user_input = input("User: ")
#            if user_input.lower() in ["quit", "exit", "q"]:
#                print("Goodbye!")
    #            summarize_conversation_and_store(config.get("configurable", {}).get("user_id", "1"))
    #            break
    #        stream_graph_updates(user_input)
    #    except KeyboardInterrupt:
    #        print("\nGoodbye!")
    #        summarize_conversation_and_store(config.get("configurable", {}).get("user_id", "1"))
    #        break
    #    except Exception as e:
    #        print(f"Unexpected error: {e}")
    #        continue

"""
    try:
        # Clear cached memory context for fresh responses on each new user input
        try:
            memory_cache.clear()
        except Exception:
            pass
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
    reply_parts = []
    try:
        # Clear cached memory context so the retrieval uses up-to-date memories
        try:
            memory_cache.clear()
        except Exception:
            pass
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
 """