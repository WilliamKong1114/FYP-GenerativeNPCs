import sqlite3
import json
import time
import re
import signal
import sys
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from dotenv import load_dotenv
import chromadb
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
from typing import Annotated, Optional

from planner import llm
from unity_comm import UnityClient
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state import AgentStateManager
from World_Environment.simulation_clock import SimulationClock
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill
from conversation_manager import ConversationManager
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

memory_cache = {}
CACHE_DURATION = 300

store = InMemoryStore()
memory = InMemorySaver()

conversation_llm = ChatVertexAI(
    model="gemini-2.5-flash",
    temperature=0,
    max_tokens=None,
    max_retries=6,
    stop=None,
)

class State(TypedDict):
    messages: Annotated[list, add_messages]

def generate_new_skill(action_desc, agent_state=None, relevant_skills=None, last_code=None, error=None):
    guidelines = """
    Guidelines:
    1. Your function will be reused for building more complex functions. Therefore, you should make it generic and reusable.
    2. Write VALID Python code. Do NOT wrap in markdown blocks. Do NOT provide explanations.
    3. The code should extract target from params: `target = params.get('target_name')`
    4. The code MUST end by setting variable `result` to an estimated duration (float in seconds) for the action. E.g., `result = 4.0`.
    """
    
    primitives = """
    Control Primitives:
    - Variable `unity` is a UnityClient instance.
    - Variable `params` is a dictionary containing 'target_name' and 'agent_id'.
    - Use `unity.move_to(target_name, description, agent_id=params.get('agent_id'))` to move.
    - Use `unity.interact(target_name, method_name, agent_id=params.get('agent_id'))` to act. Method names are usually verbs like 'Till', 'Water', 'Harvest'.
    """
    
    skills_context = ""
    if relevant_skills:
        skills_context = "Relevant Skills from Library:\n"
        for s in relevant_skills:
            desc = s.get('doc') or s.get('description') or "No description"
            code = s.get('metadata', {}).get('code') or "# No code"
            skills_context += f"--- Skill: {desc} ---\n{code}\n"
            
    feedback_section = ""
    if last_code:
        feedback_section = f"""
        Previous Code Attempt:{last_code}
        Execution Error / Feedback:{error}
        Critique:
        The previous code failed. Analyze the error and generate a fixed version.
        """
        
    state_section = f"Current Agent State: {agent_state}" if agent_state else ""
    prompt = f"""
    You are an AI generating Python code for a game agent skill. Task: {action_desc}
    {guidelines}
    {primitives}
    {skills_context}
    {state_section}
    {feedback_section}
    Generate the Python code now.
    """
    response = llm.invoke(prompt)
    code = response.content.replace("```python", "").replace("```", "").strip()
    return code

def resolve_and_execute_skill(action_desc, target_name, client, agent_id=None, agent_data=None):
    if agent_data and agent_data.get("is_chatting"):
        return 0.1

    #print(f"--> Searching skill for: {action_desc}")
    
    res = query_skill(action_desc, n_results=5)
    candidates = []
    if res and res.get('ids') and len(res['ids']) > 0:
        ids_list = res['ids'][0]
        dists_list = res.get('distances', [[]])[0] if res.get('distances') else []

        for i, sid in enumerate(ids_list):
            dist = dists_list[i] if i < len(dists_list) else 0.0            
            if dist > 1.0:
                continue

            doc = res['documents'][0][i] if res['documents'] else None
            meta = res['metadatas'][0][i] if res['metadatas'] else None
            candidates.append({"id": sid, "description": doc, "metadata": meta, "distance": dist})

    params = {"target_name": target_name, "action_desc": action_desc}
    if agent_id:
        params["agent_id"] = agent_id

    for skill in candidates:
        name = skill['metadata'].get('name', 'Unknown')
        print(f"--> Candidate: {name} (Dist: {skill.get('distance', 'N/A')})")
        try:
            return float(execute_skill(skill, params=params, unity_client=client))
        except Exception as e:
            print(f"--> Skill '{name}' execution failed: {e}")
            continue

    #print(f"--> No suitable skill found or executed for: {action_desc}")
    return 3.0

def generate_emojis(actions):
    actions_formatted = "\n".join([f"{i+1}. {act}" for i, act in enumerate(actions)])    
    prompt = (
        "You are an emoji translator. For each action in the numbered list below, "
        "provide exactly two emojis that best represent it. Do not add or include any gender signs or symbols.\n"
        "Return ONLY a JSON list of strings, where each string contains the two emojis. "
        "Do not include markdown formatting or numbering in the output.\n\n"
        f"Actions:\n{actions_formatted}\n\n"
        "Output Example:\n"
        '["🚶‍♂️🌲", "📖🕯️", "😴🌙"]'
    )
    
    response = llm.invoke(prompt)
    content = response.content.strip()
    
    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "")
    if content.startswith("```"):
        content = content.replace("```", "")
    
    emoji_list = json.loads(content)            
    return emoji_list
    
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

def get_cached_memory_context(query: str, user_id: str) -> str:
    """Get memory context with caching to avoid repeated database queries"""
    cache_key = f"{user_id}:{hash(query)}"
    current_time = time.time()
    
    if cache_key in memory_cache:
        cached_data, timestamp = memory_cache[cache_key]
        if current_time - timestamp < CACHE_DURATION:
            return cached_data
    
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
        
        memory_cache[cache_key] = (memory_context, current_time)
        return memory_context
    except Exception as e:
        print(f"Error retrieving memory context: {e}")
        return ""

def agent_node(state: State, config: RunnableConfig):
    conf = config.get("configurable", {})
    user_id = conf.get("user_id", "1")
    agent_name = conf.get("agent_name", "Agent")
    agent_persona = conf.get("agent_persona", "You are a friendly villager.")
    
    if state["messages"]:
        last_message = state["messages"][-1].content
        memory_context = get_cached_memory_context(last_message, user_id)
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
        - DO NOT start every message with "Morning", "Hello", or the partner's name. Use greetings only occasionally.
        - Use short sentences, contractions, and everyday language. 
        - Avoid sounding overly formal or poetic. 
        - Keep it simple and conversational, like chatting with a friend. 
        - Avoid repeating previous statements and topics unless necessary.
        - Adapt responses to the user's latest input and keep them fresh.
        - Determine when to ask questions to keep the conversation flowing, but avoid asking too many in a row.
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
            if normalized_role in ("human", "human_user"):
                normalized_role = "user"
            if normalized_role not in ("system", "user", "assistant"):
                normalized_role = "user"
            user_msgs.append({"role": normalized_role, "content": content.strip()})

    msgs = [{"role": "system", "content": system_prompt}] + user_msgs
    response = conversation_llm.invoke(msgs)
    return {"messages": [response]}

builder = StateGraph(State)
tools = [human_assistance, saveUserInfo, getUserInfo]
builder.add_node("agent", agent_node)
tool_node = ToolNode(tools=tools)
builder.add_node("tools", tool_node)
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
builder.set_entry_point("agent")
builder.add_edge("agent", END)

graph = builder.compile(checkpointer=memory, store=store)

def generate_agent_response(agent_id: str, agent_persona: str, triggering_msg: str, sender_id: str, thread_id: str = None) -> str:
    """Generate response for an agent using LangGraph"""
    run_config = {
        "configurable": {
            "thread_id": thread_id or f"{agent_id}-conversation",
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

def summarize_conversation_and_store(user_id: str, raw_log: str = None, log_id: str = None) -> str:
    """Summarize and store conversation in memory"""
    try:
        memory_cache.clear()
        if not raw_log:
            return None

        convo_Length = 100
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
        user_msg = {"role": "user", "content": f"Summarize the following conversation into one concise informative sentence:\n\n{raw_log}"}

        resp = conversation_llm.invoke([system, user_msg])
        summary = getattr(resp, "content", None) or str(resp)

        manage_data.add_memories([summary], user_id=user_id)
        manage_data.save_user_summary(user_id, summary, log_id=log_id)

        #print(f"--- Conversation summary for {user_id} saved ---")
        print(summary)
        return summary
    except Exception as e:
        print(f"Failed to summarize conversation for {user_id}: {e}")
        return None

def get_plan(user_id: str = "Samson"):
    conn = sqlite3.connect("plans.db")
    cur = conn.cursor()
    try:
        cur.execute("SELECT plan_json, description FROM plans WHERE user_id = ? ORDER BY created_on DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
    except Exception as e:
        print(f"Error reading DB: {e}")
        return None, []
    finally:
        conn.close()

    if not row:
        return None, []

    plan_json_str = row[0]
    plan_data = json.loads(plan_json_str)        
    return plan_data.get("description", ""), plan_data.get("emojis", [])

def parse_plan_steps(description):
    lines = description.split('\n')
    steps = []
    # Regex for "1) 7:00 am: Action text"
    # Matches: number, paren, space, time, colon, space, action
    pattern = re.compile(r'\d+\)\s+(\d+:\d+\s+[ap]m):\s+(.*)')
    
    for line in lines:
        line = line.strip()
        match = pattern.match(line)
        if match:
            time_str = match.group(1)
            action_text = match.group(2)
            steps.append((time_str, action_text))
    return steps

def parse_time_to_minutes(time_str):
    match = re.search(r'(\d+):(\d+)\s*([ap]m)', time_str.lower())
    if not match: return 0
    h, m, p = int(match.group(1)), int(match.group(2)), match.group(3)
    if p == 'pm' and h < 12: h += 12
    if p == 'am' and h == 12: h = 0
    return h * 60 + m

# Global shutdown flag and locks
shutdown_requested = False
state_lock = threading.Lock()

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    global shutdown_requested
    print("\n[SHUTDOWN] Interrupt received, gracefully closing connections...")
    shutdown_requested = True

def execute_agent_action(agent_id, action, emojis, tree, client, state_manager, agent_data):
    """Thread-safe wrapper for pathfinding and execution in parallel"""
    try:
        # Move pathfinding logic into the thread to avoid blocking main loop
        with state_lock:
            agent_state_data = state_manager.state.get("agents", {}).get(agent_id, {})
        
        current_area = agent_state_data.get("interaction_area", "Unknown Area")
        agent_context = f"[Agent's Location Context] {agent_id} is currently in {current_area}. Prefer to stay in the current area if the activity can be done there."
        
        path_nodes = tree.find_suitable_location(action, agent_context)

        # CHECK BEFORE STARTING UNITY COMMAND
        if agent_data.get("is_chatting"):
            # print(f"[THREAD] {agent_id} aborted action '{action}' because conversation started")
            return 0.1

        target_name = None
        full_action_desc = action
        area_name = "unknown"
        obj_name = "unknown"

        if path_nodes:
            target_node = path_nodes[-1]
            target_name = tree.get_location(target_node)
            path_str = ": ".join([n.name for n in path_nodes])
            full_action_desc = f"{action} @ {path_str}"
            
            # Determine area and object from target node
            if target_node.node_type == "object":
                obj_name = target_node.name
                area_name = target_node.parent.name if target_node.parent else "World"
            else:
                obj_name = "unknown"
                area_name = target_node.name
        
        if not target_name:
            print(f"[⚠️ WARNING] {agent_id} has no target for '{action}', just showing dialogue.")
            client.show_dialogue(emojis, agent_id=agent_id)
            return 2.0

        print(f"[🏃 ACTION] {agent_id} starting: {action} at {target_name}")
        client.move_to(target_name, emojis, action, agent_id=agent_id)
        
        with state_lock:
            state_manager.update_agent(agent_id, full_action_desc, area=area_name, interaction_object=obj_name)
        
        duration = resolve_and_execute_skill(action, target_name, client, agent_id=agent_id, agent_data=agent_data)
        print(f"[✅ COMPLETED] {agent_id} action finished in {duration}s")
        return duration
    except Exception as e:
        print(f"[THREAD] {agent_id} error: {e}")
        return 3.0

def execute_plan():
    agents_config = [
        {
            "id": "Samson",
            "persona": ("Innate traits: friendly, outgoing."
                "Samson is a young villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge."
                "He was born to a farming family and learned from an early age how to tend crops, care for simple tools, and respect the rhythms of the seasons."
                "He enjoys helping others like growing fruit or vegetables, fishing, and woodworking. "
                "He has a small workshop where he crafts simple furniture and tools. "
                "Samson is also keen on learning new skills from travelers passing through the village.\n "
                "Goals: Improve his woodworking skills to create more intricate furniture, expand his garden to include a wider variety of plants, and build stronger relationships within the village community, and busy to get ready for the coming winter.")
        },
        {
            "id": "Jimmy",
            "persona": ("Innate traits: calm, dull, unpleasant."
            "Jimmy is a 53‑year‑old villager who has spent his entire life in a modest medieval settlement nestled between rolling pasturelands and a slow‑moving river. Behind the village lie dense woodlands where he often walks to gather herbs and fallen branches."
            "He was raised in a family known for their skill in maintaining tools and tending livestock, and from a young age he learned patience, precision, and the value of steady work. Over decades, Edric became respected for his reliability and quiet wisdom."
            "He enjoys repairing equipment for farmers, carving wooden utensils and small household items, and preparing simple herbal mixtures he learned from an elderly healer many years ago. His workshop—an aging shed filled with tools, scraps of wood, and half‑finished projects—is where he spends most afternoons."
            "His normal daily routine includes checking on neighbors’ tools that need fixing, tending a small patch of vegetables behind his home, taking quiet walks in the woods to gather materials, and chatting with travelers to hear news of faraway lands. In the evenings, he often sits by the communal fire, sharing stories or offering advice to younger villagers.")
        }
    ]
    
    global shutdown_requested
    shutdown_requested = False
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, signal_handler)  # Unix systems
    
    tree = EnvironmentTree()
    tree.load()
    
    client = UnityClient()
    state_manager = AgentStateManager()
    clock = SimulationClock(time_scale=90.0)
    conv_manager = ConversationManager(generate_response_func=generate_agent_response)
    
    num_agents = len(agents_config)
    max_workers = min(num_agents + 2, 20)
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Agent")
    print(f"[THREAD POOL] Initialized with {max_workers} workers for {num_agents} agents")
    print(f"[INFO] Press Ctrl+C to gracefully shutdown and close all connections")
    
    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "is_chatting": False,
            "active_task": None,  # Track running future
            "task_count": 0  # Track completed tasks for monitoring
        } for config in agents_config
    }

    last_day_loaded = -1
    try:
        while not shutdown_requested:
            sim_days, cur_h, cur_m = clock.get_sim_time()
            current_sim_total_minutes = cur_h * 60 + cur_m
            
            # 1. Populate agent states from state manager for conversation detection
            state_manager.refresh_state() 
            current_agent_states = []
            for a_id, a_state in state_manager.state.get("agents", {}).items():
                # Only include agents that exist in our config
                if a_id in agent_executions:
                    current_agent_states.append({
                        "id": a_id, 
                        "state": a_state,
                        "persona": agent_executions[a_id]["persona"]
                    })

            # Load new plan at the start of each simulation day
            if clock.is_new_day() and sim_days > last_day_loaded:
                print(f"\n--- New Simulation Day - {clock.get_time_string()} ---")
                for agent_id, data in agent_executions.items():
                    description, emojis = get_plan(agent_id)
                    data["steps"] = parse_plan_steps(description) if description else []
                    data["emojis"] = emojis
                    data["current_step"] = 0
                    print(f"[{agent_id}] Loaded plan for {agent_id} with {len(data['steps'])} steps.")
                last_day_loaded = sim_days

            # 2. Group agents for conversations by interaction area
            agents_by_group = {}
            for agent in current_agent_states:
                area = agent["state"].get("interaction_area", "unknown")
                
                # If area is a path string, take the specific part
                if ":" in area:
                    area = area.split(":")[-1].strip()
                
                if area and area != "unknown":
                    agents_by_group.setdefault(area, []).append(agent)

            # 3. Detect and Run Conversations (blocks main thread while active)
            all_grouped_agents = set()
            for area, group in agents_by_group.items():
                if len(group) >= 2:
                    agent_ids = [a['id'] for a in group]
                    if conv_manager.start_conversation(group):
                        all_grouped_agents.update(agent_ids)
                        
                        # Stop ongoing Unity actions for participants
                        for a_id in agent_ids:
                            agent_executions[a_id]["is_chatting"] = True
                            client.stop(agent_id=a_id)

                        loc = group[0]["state"].get("location", "unknown")
                        print(f"\n--- Conversation Triggered: {', '.join(agent_ids)} at {area} ({loc}) ---")
                        context = f"{', '.join(agent_ids)} are in the {area} near {loc}."
                        
                        for turn in conv_manager.generate_dialogue(group, context):
                            speaker = turn["speaker"]
                            text = turn["text"]
                            print(f"\n   [💬 DIALOGUE] {speaker}: {text}")
                            client.show_dialogue("💬", agent_id=speaker)
                            time.sleep(1.5)
                        
                        # After conversation ends, set a temporary busy period to force agents to move apart
                        # and prevent immediate re-triggering of the same group
                        for a_id in agent_ids:
                            agent_executions[a_id]["is_chatting"] = False
                            # Add a small buffer (e.g. 5s) where they won't pick up new tasks 
                            # while they might still be standing next to each other
                            agent_executions[a_id]["is_busy_until"] = time.time() + 5.0

            # 4. Check completed tasks and update agent states
            for agent_id, data in agent_executions.items():
                if data["active_task"] is not None:
                    if data["active_task"].done():
                        try:
                            duration = data["active_task"].result()
                            data["is_busy_until"] = time.time() + duration
                            data["current_step"] += 1
                            data["task_count"] += 1
                            data["active_task"] = None
                        except Exception as e:
                            print(f"--> [{agent_id}] Task error: {e}")
                            data["active_task"] = None
                            data["current_step"] += 1
            
            # 5. Submit new tasks for agents that are ready (NOT chatting)
            active_count = sum(1 for d in agent_executions.values() if d["active_task"] is not None)
            
            for agent_id, data in agent_executions.items():
                # Only start new task if: has steps, not busy, no active task, AND NOT CHATTING
                if (data["current_step"] < len(data["steps"]) and 
                    time.time() >= data["is_busy_until"] and 
                    data["active_task"] is None and
                    not data.get("is_chatting", False)):
                    
                    time_str, action = data["steps"][data["current_step"]]
                    scheduled_minutes = parse_time_to_minutes(time_str)

                    # Is it time for this step?
                    if current_sim_total_minutes >= scheduled_minutes:
                        print(f"\n[{clock.get_time_string()}] Agent {agent_id} Starting: {action} (Active threads: {active_count}/{max_workers})")
                        emojis = data["emojis"][data["current_step"]] if data["current_step"] < len(data["emojis"]) else "🤖❓"
                        
                        try:
                            # Submit to thread pool. Pathfinding now happens INSIDE the thread.
                            future = executor.submit(
                                execute_agent_action,
                                agent_id, action, emojis, tree, client, state_manager, data
                            )
                            data["active_task"] = future
                            active_count += 1
                        except Exception as e:
                            print(f"--> [{agent_id}] Failed to submit task: {e}")
                            data["current_step"] += 1

            state_manager.set_time(clock.get_time_string())
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] KeyboardInterrupt caught...")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # ALWAYS execute cleanup, regardless of how loop exits
        print("\n[SHUTDOWN] Cleaning up resources...")
        
        # 1. Stop accepting new tasks and wait for active tasks to complete
        print("[SHUTDOWN] Waiting for active agent tasks to complete...")
        executor.shutdown(wait=True, cancel_futures=False)
        print("[SHUTDOWN] All agent tasks completed")
        
        # 2. Close all persistent connections (one per agent)
        print("[SHUTDOWN] Closing all persistent agent connections...")
        client.close()  # Closes all agent persistent connections
        print("[SHUTDOWN] All connections closed")
        
        print("[SHUTDOWN] Complete - Safe to exit")

if __name__ == "__main__":
    try:
        execute_plan()
    except SystemExit:
        print("\n[EXIT] Program terminated")
    except Exception as e:
        print(f"\n[FATAL] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
