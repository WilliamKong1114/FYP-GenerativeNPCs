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
from World_Environment.agent_state_manager import AgentStateManager
from World_Environment.area_state_manager import area_system
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

def get_graph():
    builder = StateGraph(State)                                 #initialization & receive message
    builder.add_node("agent", agent_node)                       
    builder.add_node("tools", ToolNode(tools=tools))            
    builder.add_conditional_edges("agent", tools_condition)     #deciding whether to save/retrieve memories
    builder.add_edge("tools", "agent")           #accessing tools, retrieve memories back to agent
    builder.set_entry_point("agent")             #agent as the entry point
    builder.add_edge("agent", END)               #returning response
    graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())
    return graph

def parse_plan(description: str):
    lines = description.split('\n')
    steps = []
    # Example: "15) 13:00: Head to the workshop to gather materials for crafting furniture."
    # \d+\) - 1); \s - whitespace; \d+:\d+\s+[ap]m - 6:00 am
    pattern = re.compile(r'\d+\)\s+(\d+:\d+):\s+(.*)')
    
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
#state_lock = threading.Lock()
chat_lock = threading.Lock()


def signal_handler(sig, frame):
    global shutdown
    shutdown = True

def find_target(action: str, tree: EnvironmentTree, agent_data):
    path_nodes = tree.find_suitable_location(action, agent_data)
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
    
def execute_agent_action(agent_id, action, emojis, tree, client, state_manager, agent_data, cur_time, conv_manager, agent_executions):
    
    target_result = find_target(action, tree, agent_data)
    target_name, action_desc, area_name, obj_name = target_result
    
    print(f"[{cur_time}] {agent_id}: {action} at {target_name}")
    client.move_to(target_name, emojis, action, agent_id, wait_for_response=True)

    area_manager = area_system.get_manager(area_name)
    with area_manager.lock:
        area_manager.load_state()
        current_state = area_manager.get_area_state()
        obj_info = current_state.get(obj_name, {})

        if obj_info.get("state") == "occupied" and obj_info.get("occupied_by") != agent_id:
            print(f"[{cur_time}] {agent_id}: {obj_name} is occupied by {obj_info.get('occupied_by')}")
            return 3.0

        area_manager.set_area_state(obj_name, "occupied", agent_id)

    #time.sleep(2)
    #duration = resolve_and_execute_skill(action_desc, target_name, client, agent_id, agent_data)
    
    with area_manager.lock:
        area_manager.load_state() 
        area_manager.set_area_state(obj_name, "empty", None) # Action finished
        agents_nearby = area_manager.get_agents_in_area()
        potential_partners = [a for a in agents_nearby if a != agent_id]

    if potential_partners and not agent_executions[agent_id]["is_chatting"]:
        partner_id = potential_partners[0]

        if agent_id > partner_id:  #Avoid both agent running the logic
            return

        with chat_lock:
            if not agent_executions[agent_id]["is_chatting"] and not agent_executions[partner_id]["is_chatting"]:
                agent_executions[agent_id]["is_chatting"] = True
                agent_executions[partner_id]["is_chatting"] = True
                should_start = True
            else:
                should_start = False
        
        if should_start:
            client.move_to(target_name, "", action, agent_id, wait_for_response=True)
        
            client.set_chatting(agent_id, "start");
            client.set_chatting(partner_id, "start");

            group = [
                {"id": agent_id, "persona": agent_executions[agent_id]["persona"]}, 
                {"id": partner_id, "persona": agent_executions[partner_id]["persona"]}
            ]

            if conv_manager.start_conversation(area_name, group):
                print(f"[{cur_time}] {agent_id} found {partner_id} in {area_name}. Starting chat...")
                conv_manager.handle_conversation(area_name, group, agent_executions=agent_executions, client=client)            
            
            client.set_chatting(agent_id, "stop");
            client.set_chatting(partner_id, "stop");
            
            with chat_lock:
                agent_executions[agent_id]["is_chatting"] = False
                agent_executions[partner_id]["is_chatting"] = False
            
        state_manager.set_agent_state(area_name, agent_id, action_desc, obj_name)
    #return duration
  
def main():
    agents_config = [
        {
            "id": "Samson",
            "persona": ("Innate traits: friendly, outgoing."
            "Samson is a young villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge."
            "He was born to a farming family and learned from an early age how to tend crops, care for simple tools, and respect the rhythms of the seasons."
            "He is boring and don't like to social with others."
            "He has a small workshop where he crafts simple furniture and tools."
            "Samson is being focused by his parent on learning new skills woodworking skills for better use.")
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
    #signal.signal(signal.SIGINT, signal_handler)
    
    tree = EnvironmentTree()
    tree.load()
    
    client = UnityClient()
    agent_state_manager = AgentStateManager()
    area_system.start_listener(5006)

    clock = SimulationClock(time_scale=300) #1 real seconds = 5 simulated minutes
    conv_manager = ConversationManager(graph=get_graph(), clock=clock, debug_mode=False)
    
    num_agents = len(agents_config)
    max_workers = min(num_agents + 1, 20)
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
            for agent_id in [config["id"] for config in agents_config]:
                client.check_for_incoming(agent_id, agent_executions)

            if clock.is_new_day():
                simulation_active = False
                print(f"\n--- New Day - {clock.get_time_string()} ---")
                for agent_id, data in agent_executions.items():
                    description, emojis = get_plan(agent_id)
                    data["agent_name"] = agent_id
                    data["steps"] = parse_plan(description)
                    data["emojis"] = emojis
                    data["current_step"] = 0
                    print(f"[{agent_id}] Loaded plan for {agent_id} with {len(data['steps'])} steps.")
                simulation_active = True

            if (simulation_active and clock.get_sim_hour() >= 6):
                for agent_id, data in agent_executions.items():
                    is_busy = data["active_task"] is not None and not data["active_task"].done()
                    is_cooldown = time.time() < data["is_busy_until"]

                    if (not is_busy and not is_cooldown and not data["is_chatting"] and data["current_step"] < len(data["steps"])):    # has tasks remaining
                        step_index = data["current_step"]
                        action = data["steps"][step_index]
                        cur_time = clock.get_time_string()
                        step_emoji = ""
                        if "emojis" in data and isinstance(data["emojis"], list) and step_index < len(data["emojis"]):
                            step_emoji = data["emojis"][step_index]
                            if isinstance(step_emoji, list):
                                step_emoji = "".join(step_emoji)
                                
                        future = executor.submit(
                            execute_agent_action, agent_id, action[1], step_emoji, tree, client, 
                            agent_state_manager, data, cur_time, conv_manager, agent_executions
                        )

                        data["active_task"] = future
                        data["is_busy_until"] = time.time() + 6  # Wait 6 real-world seconds
                        data["current_step"] += 1

            if simulation_active:
                agent_state_manager.set_time(clock.get_time_string())
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] KeyboardInterrupt caught...")
        shutdown = True
    finally:        
        executor.shutdown(wait=False, cancel_futures=True)
        print("[SHUTDOWN] All agent tasks completed")
        area_system.stop_listener()
        client.close()
        print("[SHUTDOWN] All connections closed")
        agent_state_manager.reset_agents()
        area_system.reset_all()
        print("[SHUTDOWN] Complete")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        print("\n[EXIT] Program terminated")