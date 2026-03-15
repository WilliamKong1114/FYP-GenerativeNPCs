import sqlite3, json, os, time, re, signal, datetime, threading, hashlib
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
from Secure.llm_config import skill_llm, observe_llm, dialogue_llm
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state_manager import AgentStateManager
from World_Environment.area_state_manager import AreaSystem
from World_Environment.simulation_clock import SimulationClock
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill
from conversation_manager import ConversationManager
from preference_manager import PreferenceManager
from openai import APITimeoutError
from chroma_client import get_client
chroma_client = get_client(path="./chroma_db")

from agent_memory import AgentMemoryManager
import manage_data
import reflection

load_dotenv()
agent_state_manager = AgentStateManager()
area_state_manager = AreaSystem()
memory_manager = AgentMemoryManager()
clock = SimulationClock(time_scale=300) #1 real seconds = 5 simulated minutes
tree = EnvironmentTree()
tree.load()


@lru_cache(maxsize=2)
def get_collection(name: str):
    return chroma_client.get_or_create_collection(name)

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

#CACHE_DURATION = 300
#memory_cache = TTLCache(maxsize=1024, ttl=CACHE_DURATION)

def get_memory(query: str, user_id: str, partner_id: str = None):
    try:
        results = get_collection("memories").query(
            query_texts=[query],
            n_results=10,
            where={"user_id": user_id}
        )

        if not results["documents"] and len(results["documents"][0]) == 0:
            return ""

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        current_hours = clock.get_sim_hour()
        retrieved_memories = []

        for doc, meta, dist in zip(documents, metadatas, distances):
            relevance = 1.0 / (1.0 + dist)
            importance = meta.get("importance", 3) / 10.0

            last_accessed = meta.get("modified_on", 0)
            delta_t = max(0, current_hours - last_accessed)
            recency = pow(0.99, delta_t)

            final_score = (0.5 * recency) + (0.3 * importance) + (0.2 * relevance)

            if partner_id and partner_id.lower() in doc.lower():
                final_score *= 1.5
            
            retrieved_memories.append((doc, final_score))

        retrieved_memories.sort(key=lambda x: x[1], reverse=True)
        top_memories = [m[0] for m in retrieved_memories[:3]]
        
        return f"\nRelevant memories: {top_memories}"
        #Return example: "\nRelevant memories: [memory1, memory2, memory3]"

    except Exception as e:
        print(f"Error retrieving memory context: {e}")
        return ""

def agent_node(state: State, config: RunnableConfig):
    conf = config.get("configurable")
    user_id = conf.get("user_id")
    agent_name = conf.get("agent_name")
    agent_persona = conf.get("agent_persona")
    partner_id = conf.get("partner_id")
    
    user_msgs = []
    for m in state.get("messages", []):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        
        if isinstance(content, str) and content.strip():
            text = content.strip()
            role = str(role).lower()
            user_msgs.append({"role": role, "content": text})

    if (user_msgs):    
        memory_context = get_memory(user_msgs[-1]["content"], user_id, partner_id)
    else:
        memory_context = ""
    
    partner_context = ""
    if partner_id:
        partner_context = f"You are currently talking to {partner_id}. Recognize them as your conversation partner and use 'we', 'you', and 'us' appropriately when referring to shared plans or activities."
    
    system_prompt = f"""
        You are {agent_name}, a villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge.
        {agent_persona}
        {partner_context}
        Use memory tools to remember and recall information about users. 
        Minimize greetings, salutations, or sign-offs.
        Access the memory context to make the conversation relevant to current situation: {memory_context}.
        
        Respond in a way that fits your personality.
        - Keep your responses around 25 words
        - DO NOT start every message with "Morning", "Hello", or the partner's name. Use greetings that fits your personality.
        - Use contractions, and everyday language. 
        - Avoid sounding overly formal or poetic. 
        - Avoid repeating previous statements and topics unless necessary.
        - Adapt responses to the user's latest input and keep them fresh.
        - Determine when to ask questions to keep the conversation flowing, but avoid asking too many in a row.
    """

    response = dialogue_llm.invoke([{"role": "system", "content": system_prompt}] + user_msgs)
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
    response = skill_llm.invoke(prompt)
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

def find_target(action: str, agent_data):
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

def record_observation(agent_id: str, area_name: str, obj_name: str, action: str, client, agent_executions: dict):
    if area_name is None:
        return

    user_content = (
        f"Agent: {agent_id}\n"
        f"About to perform: {action}\n"
        f"Current location: {area_name}\n"
        f"Current object using: {obj_name}\n"
    )

    system_msg = {
        "role": "system",
        "content": (
            "You are writing an observation record for a simulated village agent."
            "Write 1 concise sentences (under 15 words) describing what the agent perceives upon arriving at the location, what he/she is trying to do, or what is he/she about to do, in third-person."
            "Be natural, precise and specific — describe the state of objects related to the agent's action."
            "Avoid sounding overly formal or poetic."
            "Examples:\n"
            "\"Samson occupied the table in workshop to craft items using bare materials.\"\n"
            "\"The well is being used by Samson to draw some water.\""
            "\"Samson is discussing the weather with Lily.\"\n"
        )
    }
    user_msg = {"role": "user", "content": user_content}

    response = observe_llm.invoke([system_msg, user_msg])
    obs_text = response.content.strip()
    
    manage_data.add_memories([obs_text], user_id=agent_id, importance=3, game_hour=clock.get_sim_hour())
    memory_manager.add_observation(agent_id, obs_text, area_name)

    #reflection.check_reflect(agent_id, clock, agent_executions, client)

def execute_agent_action(agent_id, action, emojis, client, state_manager, agent_data, cur_time, conv_manager, agent_executions):
    prev_obj = agent_data.get("current_target")
    prev_area = agent_data.get("current_area")
    agent_data["prev_target"] = prev_obj
    agent_data["prev_area"] = prev_area

    target_name, action_desc, area_name, obj_name = find_target(action, agent_data)
    area_manager = area_state_manager.get_manager(area_name)

    print(f"[{cur_time}] {agent_id}: {action} at {target_name}")
    client.move_to(target_name, emojis, action, agent_id, wait_for_response=True)
    if (area_name != prev_area):
        area_manager.set_agent_in_area(agent_id, area_name, "enter")
        prev_area_manager = area_state_manager.get_manager(prev_area)
        with prev_area_manager.lock:
            prev_area_manager.set_obj_state(prev_obj, "empty", None)
            prev_area_manager.set_agent_in_area(agent_id, prev_area, "exit")

    #record_observation(agent_id, area_name, obj_name, action, client=client, agent_executions=agent_executions)
    reflection.check_reflect(agent_id, clock, agent_executions, client)

    #Observe area state
    with area_manager.lock:
        obj_info = area_manager.get_area_state().get(obj_name)

        if not obj_info:
             obj_info = {"state": "empty"}

        if obj_info.get("state") == "occupied" and obj_info.get("occupied_by") != agent_id:
            print(f"[{cur_time}] {agent_id}: {obj_name} is occupied by {obj_info.get('occupied_by')}")
            agent_data["current_target"] = obj_name
            agent_data["current_area"] = area_name
        else:
            area_manager.set_obj_state(obj_name, "occupied", agent_id)

        #time.sleep(2)
        #duration = resolve_and_execute_skill(action_desc, target_name, client, agent_id, agent_data)
        agents_nearby = area_manager.get_agents_in_area()
        potential_partners = [a for a in agents_nearby if a != agent_id]

    agent_data["current_target"] = obj_name
    agent_data["current_area"] = area_name

    if potential_partners and not agent_executions[agent_id]["is_chatting"]:
        partner_id = preference_manager.select_partner(agent_id, potential_partners)
        if not partner_id:
            return

        if agent_executions[partner_id]["is_chatting"]:
            return

        group = [
            {"id": agent_id, "persona": agent_executions[agent_id]["persona"]},
            {"id": partner_id, "persona": agent_executions[partner_id]["persona"]}
        ]
        conv_manager.check_conversation(area_name, group, agent_executions, client)
        state_manager.set_agent_state(agent_id, action_desc)
    #return duration
  
def main():
    global preference_manager
    preference_manager = PreferenceManager()

    agents_state = agent_state_manager.get_agent_state()
    agents_config = [
        {
            "id": name,
            "persona": data["persona"],
            "home_node": data["home_node"],
            "home_area": data["home_area"]
        }
        for name, data in agents_state.items()
    ]

    global shutdown
    shutdown = False    
    
    client = UnityClient()
    #area_state_manager.start_listener(5006)
    conv_manager = ConversationManager(graph=get_graph(), clock=clock, debug_mode=False, preference_manager=preference_manager)
    client.conv_manager = conv_manager  # Inject for handling incoming requests
    
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
            "last_conv_time": 0,
            "is_chatting": False,
            "is_reflecting": False,
            "active_task": None,    # Track running future
            "current_target": config["home_node"],  # Track current target node
            "current_area": config["home_area"],    # Track current area
            "prev_target": None,
            "prev_area": None
        } for config in agents_config
    }

    try:
        while not shutdown:   
            for agent_id in [config["id"] for config in agents_config]:
                client.check_for_incoming(agent_id, agent_executions)

            if clock.is_new_day():
                simulation_active = False

                for config in agents_config:
                    agent_id = config["id"]
                    data = agent_executions[agent_id]
                    home_node = config["home_node"]
                    home_area = config["home_area"]
                    if data["active_task"] and not data["active_task"].done():
                        data["active_task"].result()  # Wait for current task to finish

                    while data["is_chatting"]:
                        time.sleep(1)  # Wait for chat to finish

                    client.move_to(home_node, "", "Return Home", agent_id, wait_for_response=True)
                agent_state_manager.reset_agents()
                area_state_manager.reset_area()

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

                    if (not is_busy and not is_cooldown and not data["is_chatting"] and not data["is_reflecting"] and data["current_step"] < len(data["steps"])):    # has tasks remaining
                        step_index = data["current_step"]
                        action = data["steps"][step_index]
                        cur_time = clock.get_time_string()
                        step_emoji = ""
                        if "emojis" in data and isinstance(data["emojis"], list) and step_index < len(data["emojis"]):
                            step_emoji = data["emojis"][step_index]
                            if isinstance(step_emoji, list):
                                step_emoji = "".join(step_emoji)
                                
                        future = executor.submit(
                            execute_agent_action, agent_id, action[1], step_emoji, client, 
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
        #area_state_manager.stop_listener()
        client.close()
        print("[SHUTDOWN] All connections closed")
        agent_state_manager.reset_agents()
        area_state_manager.reset_area()
        print("[SHUTDOWN] Complete")

if __name__ == "__main__":
    main()
