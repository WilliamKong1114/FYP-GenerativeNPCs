import sqlite3, json, time, re, signal, datetime, threading, hashlib
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from langchain_core.tools import tool
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.runnables import RunnableConfig
from typing import Annotated
from cachetools import TTLCache
from planner import get_plan
from unity_comm import UnityClient
from Secure.llm_config import skill_llm as llm
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state import AgentStateManager
from World_Environment.simulation_clock import SimulationClock
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill
from conversation_manager import ConversationManager
from openai import APITimeoutError
from chroma_client import get_client

load_dotenv()
chroma_client = get_client(path="./chroma_db")

@lru_cache(maxsize=2)
def get_collection(name: str):
    return chroma_client.get_or_create_collection(name)

# llm definition moved to llm_config.py

class State(TypedDict):
    messages: Annotated[list, add_messages]

""" @tool
def human_assistance(query: str) -> str:
    return interrupt({"query": query})
 """

@tool
def saveUserInfo(info: str, config: RunnableConfig):
    """Save user information to the database."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        get_collection("user_info").upsert(
            ids=[user_id],
            documents=[info],
            metadatas=[{"type": "user_info", "user_id": user_id}]
        )
        return f"Saved info for {user_id}."
    except Exception as e:
        return f"Error saving info: {str(e)}"

@tool
def getUserInfo(config: RunnableConfig):
    """Retrieve user information from the database."""
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        results = get_collection("user_info").get(ids=[user_id])
        if results["documents"] and len(results["documents"]) > 0:
            return results["documents"][0]
        return f"No info found for {user_id}."
    except Exception as e:
        return f"Error retrieving info: {str(e)}"

CACHE_DURATION = 300
memory_cache = TTLCache(maxsize=1024, ttl=CACHE_DURATION)

def get_cached_memory(query: str, user_id: str):
    key = f"{user_id}:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
    try:
        return memory_cache[key]        #If same query and user, return the cached memory context
    except KeyError:
        pass

    try:
        results = get_collection("memories").query(
            query_texts=[query],
            n_results=3,
            where={"user_id": user_id}
        )
        if results["documents"] and len(results["documents"][0]) > 0:
            memories = results["documents"][0]
            memory_context = f"\nRelevant memories: {memories}"
            #Return example: "\nRelevant memories: [memory1, memory2, memory3]"
        else:
            memory_context = ""
        memory_cache[key] = memory_context
        return memory_context
    except Exception as e:
        print(f"Error retrieving memory context: {e}")
        return ""

def agent_node(state: State, config: RunnableConfig):
    conf = config.get("configurable", {})
    user_id = conf.get("user_id", "1")
    agent_name = conf.get("agent_name", "Agent")
    agent_persona = conf.get("agent_persona", "You are a villager.")
    
    user_msgs, last_user_msg = [], ""
    for m in state.get("messages", []) or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        
        if isinstance(content, str) and content.strip():
            text = content.strip()
            norm_role = str(role).lower()
            if norm_role not in ("system", "assistant", "ai"):
                norm_role = "user"
                last_user_msg = text
            user_msgs.append({"role": norm_role, "content": text})

    if (last_user_msg or user_msgs):    
        memory_context = get_cached_memory(last_user_msg or (user_msgs[-1]["content"] if user_msgs else ""), user_id)
        #the latest user message is being qured to fetch relevant memories
    else:
        memory_context = ""
    
    system_prompt = f"""
        You are {agent_name}, a villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge..
        {agent_persona}
        Use memory tools to remember and recall information about users. 
        Minimize greetings, salutations, or sign-offs.
        Access the memory context to make the conversation relevant to current situation: {memory_context}.
        
        Respond in a casual, human-like tone that feels natural.
        - Keep your responses under 50 words
        - DO NOT start every message with "Morning", "Hello", or the partner's name. Use greetings only occasionally.
        - Use contractions, and everyday language. 
        - Avoid sounding overly formal or poetic. 
        - Keep it conversational, change the speaking tone depends on the opponent's identity. 
        - Avoid repeating previous statements and topics unless necessary.
        - Adapt responses to the user's latest input and keep them fresh.
        - Determine when to ask questions to keep the conversation flowing, but avoid asking too many in a row.
    """

    response = llm.invoke([{"role": "system", "content": system_prompt}] + user_msgs)
    return {"messages": [response]}

tools = [
    saveUserInfo, 
    getUserInfo,
    #human_assistance
]
builder = StateGraph(State)                                 #initialization & receive message
builder.add_node("agent", agent_node)                       
builder.add_node("tools", ToolNode(tools=tools))            
builder.add_conditional_edges("agent", tools_condition)     #deciding whether to save/retrieve memories
builder.add_edge("tools", "agent")           #accessing tools, retrieve memories back to agent
builder.set_entry_point("agent")             #agent as the entry point
builder.add_edge("agent", END)               #returning response
graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())

def generate_agent_response(agent_id: str, agent_persona: str, triggering_msg: str, sender_id: str = None, thread_id: str = None):
    #incharge of in-game conversation generation
    config = {
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
        result = graph.invoke(inputs, config)       #trigger agent_node and tools
        messages = result.get("messages", [])
        if messages:
            response_content = messages[-1].content
    except Exception as e:
        print(f"Error generating response for {agent_id}: {e}")
        response_content = "..."
    return response_content

def parse_plan(description: str):
    lines = description.split('\n')
    steps = []
    # Example: "1) 6:00 am: Wake up and go outside"
    # \d+\) - 1); \s - whitespace; \d+:\d+\s+[ap]m - 6:00 am
    pattern = re.compile(r'\d+\)\s+(\d+:\d+\s+[ap]m):\s+(.*)')
    
    for line in lines:
        line = line.strip()
        match = pattern.match(line)
        if match:
            time = match.group(1)
            action = match.group(2)
            steps.append((time, action))
    return steps

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

shutdown = False
state_lock = threading.Lock()

def signal_handler(sig, frame):
    global shutdown
    shutdown = True

def find_target(action: str, tree: EnvironmentTree, agent_context: str, agent_data):
    if agent_data.get("is_chatting"):
        return None, None, None, None
    path_nodes = tree.find_suitable_location(action, agent_context)
    if not path_nodes:
        return None, None, None, None
    
    target_node = path_nodes[-1]
    target_name = tree.get_location(target_node)
    path_str = ": ".join([n.name for n in path_nodes])
    action_desc = f"{action} @ {path_str}"
    
    if target_node.node_type == "object":
        obj_name = target_node.name
        area_name = target_node.parent.name
    else:
        obj_name = "unknown"
        area_name = target_node.name
    return target_name, action_desc, area_name, obj_name

def get_set_agent_state(state_manager, agent_id, action_desc=None, area=None, obj=None):
    with state_lock:
        agent_state = state_manager.state.get("agents", {}).get(agent_id, {})
        if action_desc:
            state_manager.update_agent(agent_id, action_desc, area=area, obj=obj)
        return agent_state

def execute_agent_action(agent_id, action, emojis, tree, client, state_manager, agent_data, cur_time):
    
    if agent_data.get("is_chatting", False):    #if chatting, skip action
        return
    
    agent_state = get_set_agent_state(state_manager, agent_id)
    current_area = agent_state.get("interaction_area", "Unknown Area")      #need to remove later
    agent_context = f"[Agent's Location Context] {agent_id} is currently in {current_area}."

    target_name, action_desc, area_name, obj_name = find_target(action, tree, agent_context, agent_data)
    print(f"[{cur_time}] {agent_id}: {action} at {target_name}")
    client.move_to(target_name, emojis, action, agent_id)
    duration = resolve_and_execute_skill(action_desc, target_name, client, agent_id=agent_id, agent_data=agent_data)
    get_set_agent_state(state_manager, agent_id, action_desc, area=area_name, obj=obj_name)
    return duration
    
def main():
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
    
    global shutdown
    shutdown = False
    signal.signal(signal.SIGINT, signal_handler)
    
    tree = EnvironmentTree()
    tree.load()
    
    client = UnityClient()
    state_manager = AgentStateManager()
    clock = SimulationClock(time_scale=90.0)
    conv_manager = ConversationManager(generate_response_func=generate_agent_response, clock=clock)
    
    num_agents = len(agents_config)
    max_workers = min(num_agents + 2, 20)
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Agent")
    
    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "is_chatting": False,
            "active_task": None,    # Track running future
        } for config in agents_config
    }

    try:
        while not shutdown:
            cur_days, cur_h, cur_m, total_min = clock.get_sim_time()
            
            with state_lock:
                state_manager.refresh_state() 
                current_agent_states = []
                for agent_id, agent_state in state_manager.state.get("agents", {}).items():
                    if agent_id in agent_executions:
                        current_agent_states.append({
                            "id": agent_id, 
                            "state": agent_state,
                            "persona": agent_executions[agent_id]["persona"]
                        })

            if clock.is_new_day():
                print(f"\n--- New Day - {clock.get_time_string()} ---")
                for agent_id, data in agent_executions.items():
                    description, emojis = get_plan(agent_id)
                    data["steps"] = parse_plan(description)
                    data["emojis"] = emojis
                    data["current_step"] = 0
                    print(f"[{agent_id}] Loaded plan for {agent_id} with {len(data['steps'])} steps.")

            agents_by_group = {}
            for agent in current_agent_states:
                area = agent["state"].get("interaction_area", "unknown")
                if ":" in area:
                    area = area.split(":")[-1].strip()     
                if area and area != "unknown":
                    agents_by_group.setdefault(area, []).append(agent)
                    #{"Center": [agent1, agent2], "Workshop": [agent3]}

            for area, group in agents_by_group.items():
                agent_ids = [a['id'] for a in group]
                if conv_manager.start_conversation(group):                        
                    for a_id in agent_ids:
                        agent_executions[a_id]["is_chatting"] = True
                        client.stop(agent_id=a_id)

                    print(f"\n--- Conversation Triggered: {', '.join(agent_ids)} at {area} ---")
                    context = f"{', '.join(agent_ids)} are in the {area}."
                    
                    for turn in conv_manager.generate_dialogue(group, context):
                        speaker = turn["speaker"]
                        text = turn["text"]
                        print(f"\n[D] {speaker}: {text}")
                        client.show_dialogue("dialogue", agent_id=speaker)
                        #time.sleep(1.5)
                    
                    for a_id in agent_ids:
                        agent_executions[a_id]["is_chatting"] = False
                        agent_executions[a_id]["is_busy_until"] = time.time()

            # Check completed tasks and update agent states
            for agent_id, data in agent_executions.items():
                if data["active_task"] is not None:
                    if data["active_task"].done():
                        duration = data["active_task"].result() or 0.0
                        data["is_busy_until"] = time.time() + duration
                        data["current_step"] += 1
                        data["active_task"] = None
            
            # Get current day count to adjust scheduled_minutes
            sim_days, _, _, _ = clock.get_sim_time()

            for agent_id, data in agent_executions.items():
                if (data["current_step"] < len(data["steps"])   # has tasks
                    and time.time() >= data["is_busy_until"]    # not busy
                    and data["active_task"] is None             # finished previous task
                    and not data.get("is_chatting", False)):    # not chatting
                    
                    for step_index in range(data["current_step"], len(data["steps"])):
                        
                        time_str, action = data["steps"][step_index]
                        dt = datetime.datetime.strptime(time_str, "%I:%M %p")
                        
                        # Absolute scheduled minutes = (Current Sim Day * 1440) + task minutes from midnight
                        # This ensures future day tasks don't start prematurely.
                        scheduled_total_min = (sim_days * 1440) + (dt.hour * 60 + dt.minute)
                        if total_min >= scheduled_total_min:
                            cur_time = clock.get_time_string()
                            step_emoji = ""
                            if "emojis" in data and isinstance(data["emojis"], list) and step_index < len(data["emojis"]):
                                step_emoji = data["emojis"][step_index]
                                if isinstance(step_emoji, list):
                                    step_emoji = "".join(step_emoji)
                                
                            future = executor.submit(
                                execute_agent_action,
                                agent_id, action, step_emoji, tree, client, state_manager, data, cur_time
                            )
                            data["active_task"] = future
                            break   # Only start one task per agent at a time

            with state_lock:
                state_manager.set_time(clock.get_time_string())
    
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] KeyboardInterrupt caught...")
        shutdown = True
    except Exception as e:
        print(f"[Error] Conversation generation failed: {e}")
    finally:        
        executor.shutdown(wait=False, cancel_futures=True)
        print("[SHUTDOWN] All agent tasks completed")
        client.close()  # Closes all agent connections
        print("[SHUTDOWN] All connections closed")
        state_manager.reset_agents()
        print("[SHUTDOWN] Complete")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        print("\n[EXIT] Program terminated")