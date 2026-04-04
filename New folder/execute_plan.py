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
from planner import get_plan, store_plan, modify_plan, parse_plan
from unity_comm import UnityClient
from Secure.llm_config import observe_llm, dialogue_llm
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state_manager import AgentStateManager
from World_Environment.area_state_manager import AreaSystem
from World_Environment.simulation_clock import SimulationClock
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill
from planner import generate_plans
from conversation_manager import ConversationManager
from preference_manager import PreferenceManager
from commitment_manager import CommitmentManager
from Interaction_manager import InteractManager
from chroma_client import get_client
chroma_client = get_client(path="./chroma_db")

from agent_memory import AgentMemoryManager
import chromaMemory_manager
import reflection_manager

load_dotenv()
agent_state_manager = AgentStateManager()
area_state_manager = AreaSystem()
memory_manager = AgentMemoryManager()
commitment_manager = CommitmentManager()
clock = SimulationClock(time_scale=150) #1 real seconds = 150 simulated seconds
tree = EnvironmentTree()
tree.load()
candidate_info = tree.build_area_list(tree.root)

@lru_cache(maxsize=2)
def get_collection(name: str):
    return chroma_client.get_or_create_collection(name)

class State(TypedDict):
    messages: Annotated[list, add_messages]

""" @tool
def human_assistance(query: str) -> str:
    return interrupt({"query": query})

@tool
def saveUserInfo(info: str, config: RunnableConfig):
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
    user_id = config["configurable"].get("user_id", "default_user")
    try:
        results = get_collection("user_info").get(ids=[user_id])
        if results["documents"] and len(results["documents"]) > 0:
            return results["documents"][0]
        return f"No info found for {user_id}."
    except Exception as e:
        return f"Error retrieving info: {str(e)}"
 """

#CACHE_DURATION = 300
#memory_cache = TTLCache(maxsize=1024, ttl=CACHE_DURATION)

def agent_node(state: State, config: RunnableConfig):
    conf = config.get("configurable")
    user_id = conf.get("user_id")
    agent_name = conf.get("agent_name")
    agent_persona = conf.get("agent_persona")
    agent_tone = conf.get("agent_tone")

    partner_id = conf.get("partner_id")

    user_msgs = []
    for m in state.get("messages", []):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        
        if isinstance(content, str) and content.strip():
            text = content.strip()
            role = str(role).lower()
            user_msgs.append({"role": role, "content": text})

    memory_context = ""
    if (user_msgs):    
        memory_context = memory_manager.get_memory([msg["content"] for msg in user_msgs], user_id, clock.get_sim_hour(), partner_id)
        
    partner_context = ""
    if partner_id:
        relationship_score = preference_manager.get_preference_score(agent_name, partner_id)
        if relationship_score is None:
            relationship_score = 3.0
        relationship_type = preference_manager.get_relationship_type(agent_name, partner_id)
        if relationship_type is None:
            relationship_type = "Stranger"
        partner_context = (f"You are currently talking to {partner_id}. {partner_id} has a {relationship_type} relationship with you. Use suitable pronoun, manner when talking."
        f"Your relationship score with {partner_id} is {relationship_score:.2f}. Use this to guide the tone and content of your conversation.")
    
    system_prompt = f"""
        The year is 1200A.D. You are {agent_name}, a villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge.
        Here is your persona for better buildup for the conversation: {agent_persona}
        {partner_context}
        Here is your tone guideline for conversation. Choose the one that fits the relationship_type ({relationship_type}): {agent_tone}.
        Use memory tools to remember and recall information about users.
        Access the memory context to make the conversation relevant to current situation: {memory_context}.
        
        Respond guideline (IMPORTANT):
        - Keep your responses around 20 words
        - DO NOT start every message with "Morning", "Hello", or the partner's name. Use greetings that fits your personality.
        - Adapt responses to the user's latest input.
        - When someone is proposing a commitment, consider saysing something vague that doesn't commit you to anything specific.
    """

    response = dialogue_llm.invoke([{"role": "system", "content": system_prompt}] + user_msgs)
    return {"messages": [response]}

tools = [
    #saveUserInfo, 
    #getUserInfo,
    #human_assistance
]

def get_graph():
    builder = StateGraph(State)                                 #initialization & receive message
    builder.add_node("agent", agent_node)                       
    builder.add_node("tools", ToolNode(tools=tools))            
    builder.add_conditional_edges("agent", tools_condition)     #deciding whether to save/retrieve memories
    builder.add_edge("tools", "agent")                          #accessing tools, retrieve memories back to agent
    builder.set_entry_point("agent")                            #agent as the entry point
    builder.add_edge("agent", END)                              #returning response
    graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())
    return graph

def find_target(action: str, agent_id: str):
    path_nodes = tree.find_suitable_location(action, agent_id)
    
    target_node = path_nodes[-1]
    target_name = tree.get_location(target_node)
    #path_str = ": ".join([n.name for n in path_nodes])
    #action_desc = f"{action} @ {path_str}"
        
    if target_node.node_type == "object":
        obj_name = target_node.name
        area_name = target_node.parent.name
    else:
        obj_name = "unknown"
        area_name = target_node.name
    return target_name, area_name, obj_name

def record_observation(agent_id: str, area_name: str, obj_name: str, action: str):
    if area_name is None:
        return
    
    agents_nearby = area_state_manager.get_manager(area_name).get_agents_in_area()
    
    user_content = (
        f"Agent: {agent_id}\n"
        f"About to perform: {action}\n"
        f"Current location: {area_name}\n"
        f"Current object using: {obj_name}\n"
        f"Other agents nearby: {agents_nearby}\n"
    )

    system_msg = {
        "role": "system",
        "content": (
            "You are writing an observation record for a simulated village agent."
            "Write 1 concise sentences (under 15 words) describing what the agent perceives at the location, what is he/she about to do, what he thinks other agents is doing in third-person."
            "Be neutral, precise and specific — describe the state of objects related to the agent's action."
            "Avoid sounding overly formal or poetic."
            "Examples:\n"
            "\"Samson occupied the table in workshop to craft items using bare materials.\"\n"
            "\"The well is being used by Samson to draw some water.\""
            "\"Samson saw Wilton is using the table.\"\n"
        )
    }
    user_msg = {"role": "user", "content": user_content}

    response = observe_llm.invoke([system_msg, user_msg])
    obs_text = response.content.strip()
    
    chromaMemory_manager.add_memories([obs_text], user_id=agent_id, importance=3, type="observation", game_hour=clock.get_sim_hour())
    memory_manager.add_observation(agent_id, obs_text, area_name)

    #reflection_manager.check_reflect(agent_id, clock, agent_executions, client)

def execute_agent_action(agent_id, action, emojis, client, agent_data, cur_time, conv_manager, agent_executions):
    prev_obj = agent_data.get("current_target")
    prev_area = agent_data.get("current_area")
    agent_data["prev_target"] = prev_obj
    agent_data["prev_area"] = prev_area
    #print("1. Storing previous location.")

    target_name, area_name, obj_name = find_target(action, agent_id)
    #print("2. Finding target.")

    if (area_name != prev_area):
        prev_area_manager = area_state_manager.get_manager(prev_area)
        with prev_area_manager.lock:
            prev_area_manager.set_obj_state(prev_obj, "empty", None)
            prev_area_manager.set_agent_in_area(agent_id, "exit")
        #print("Not staying in the same area, exiting.")
    
    area_manager = area_state_manager.get_manager(area_name)
    client.move_to(target_name, emojis, action, agent_id, wait_for_response=True)
    #print("3. Moving to target.")
    area_manager.set_agent_in_area(agent_id, "enter")
    #print("4. Setting agent in area.")

    days, hours, minutes, _ = clock.get_sim_time()
    time_str = f"{hours:02d}:{minutes:02d}"
    #print(f"[Day {days}, {time_str}] {agent_id}: {action} at {target_name}")
    client.action_recorded(
        agent_id=agent_id,
        action_text=action,
        location=target_name,
        day=days,
        time_str=time_str,
        ts=time.time()
    )

    #record_observation(agent_id, area_name, obj_name, action)
    #print("5. Record observation.")
    reflection_manager.check_reflect(agent_id, clock, agent_executions, client)
    #print("6. Check reflection.")

    #Observe area state
    with area_manager.lock:
        obj_info = area_manager.get_area_state().get(obj_name)

        if not obj_info:
             obj_info = {"state": "empty"}

        if obj_info.get("state") == "occupied" and obj_info.get("occupied_by") != agent_id:
            #print(f"[{cur_time}] {agent_id}: {obj_name} is occupied by {obj_info.get('occupied_by')}")
            agent_data["current_target"] = obj_name
            agent_data["current_area"] = area_name
        else:
            area_manager.set_obj_state(obj_name, "occupied", agent_id)

        #time.sleep(2)
        #duration = resolve_and_execute_skill(action_desc, target_name, client, agent_id, agent_data)
        agents_nearby = area_manager.get_agents_in_area()

    agent_data["current_target"] = obj_name
    agent_data["current_area"] = area_name
    #print("7. Storing current location.")

    potential_partners = [a for a in agents_nearby if a != agent_id]
    #print(f"8. Found potential partners: {potential_partners}")

    if potential_partners and not agent_executions[agent_id]["is_chatting"]:
        partner_id = preference_manager.select_partner(agent_id, potential_partners)
        #print(f"9. Selected partner: {partner_id}")
        if not partner_id:
            return

        if agent_executions[partner_id]["is_chatting"]:
            return

        group = [
            {"id": agent_id, "persona": agent_executions[agent_id]["persona"], "tone": agent_executions[agent_id]["tone"]},
            {"id": partner_id, "persona": agent_executions[partner_id]["persona"], "tone": agent_executions[partner_id]["tone"]}
        ]
        #print(f"10. Starting conversation between {agent_id} and {partner_id}")
        conv_manager.check_conversation(area_name, group, agent_executions, client)
  
def main():
    ACTION_DURATION = 5.0

    global preference_manager
    preference_manager = PreferenceManager()

    agents_state = agent_state_manager.get_agent_state()
    agents_config = [
        {
            "id": name,
            "persona": data["persona"],
            "tone": data["tone"],
            "home_node": data["home_node"],
            "home_area": data["home_area"]
        }
        for name, data in agents_state.items()
    ]

    global shutdown
    shutdown = False    
    
    client = UnityClient()
    interaction_manager = InteractManager()
    #area_state_manager.start_listener(5006)
    conv_manager = ConversationManager(
        graph=get_graph(),
        clock=clock,
        debug_mode=False,
        preference_manager=preference_manager,
    )
    #conv_manager = conv_manager  # Inject for handling incoming requests
    
    num_agents = len(agents_config)
    max_workers = min(num_agents + 1, 20)
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Agent")
    
    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "tone": config["tone"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "last_conv_time": 0,
            "is_chatting": False,
            "is_reflecting": False,
            "active_task": None,                    # Track running future
            "current_target": config["home_node"],  # Track current target node
            "current_area": config["home_area"],    # Track current area
            "prev_target": None,
            "prev_area": None,
        } for config in agents_config
    }

    try:
        for agent_id, data in agent_executions.items():
            description, emojis = get_plan(agent_id)
            data["agent_name"] = agent_id
            data["steps"] = parse_plan(description)
            data["emojis"] = emojis
            data["current_step"] = 0
            commitment_manager.remove_commitment(agent_id)
            print(f"[{agent_id}] Loaded plan for {agent_id} with {len(data['steps'])} steps.")
        
        simulation_active = True
        while not shutdown:
            
            for aid in agent_executions.keys():
                client.check_for_incoming(aid, agent_executions, interaction_manager=interaction_manager)

            if clock.is_new_day() and clock.get_sim_days() > 0:
                simulation_active = False

                for config in agents_config:
                    agent_id = config["id"]
                    data = agent_executions[agent_id]
                    home_node = config["home_node"]
                    home_area = config["home_area"]
                    if data["active_task"] and not data["active_task"].done():
                        data["active_task"].result()  # Wait for current task to finish

                    while data["is_chatting"]:
                        time.sleep(5)  # Wait for chat to finish

                    client.move_to(home_node, "", "Return Home", agent_id, wait_for_response=True)

                agent_state_manager.reset_agents()
                area_state_manager.reset_area()

                generate_plans(agents_state, candidate_info)

                # Reload freshly generated plans and clear transient runtime flags.
                for config in agents_config:
                    agent_id = config["id"]
                    data = agent_executions[agent_id]
                    description, emojis = get_plan(agent_id)
                    data["steps"] = parse_plan(description)
                    data["emojis"] = emojis
                    data["current_step"] = 0
                    data["is_busy_until"] = 0
                    data["is_chatting"] = False
                    data["is_reflecting"] = False
                    data["active_task"] = None
                    data["current_target"] = config["home_node"]
                    data["current_area"] = config["home_area"]
                    data["prev_target"] = None
                    data["prev_area"] = None
                    commitment_manager.remove_commitment(agent_id)
                simulation_active = True
                print(f"\n--- New Day - {clock.get_time_string()} ---")

            if (simulation_active and clock.get_sim_hour() >= 6):
                for agent_id, data in agent_executions.items():

                    db_desc, db_emojis = get_plan(agent_id)
                    current_desc = "\n".join([f"{i+1}) {t}: {a}" for i, (t, a) in enumerate(data["steps"])])
                    if db_desc != current_desc:
                        #print(f"[{agent_id}] Detected updated plan, reloading...")
                        data["steps"] = parse_plan(db_desc)
                        data["emojis"] = db_emojis

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
                            execute_agent_action, agent_id, action[1], step_emoji, client, data, cur_time, conv_manager, agent_executions
                        )
                        #print("11. One Execution finished.")
                        data["active_task"] = future
                        data["is_busy_until"] = time.time() + ACTION_DURATION  # Wait for the action duration
                        data["current_step"] += 1

            if simulation_active:
                current_time = clock.get_time_string()
                if agent_state_manager.state.get("time") != current_time:
                    agent_state_manager.set_time(current_time)
                    client.update_time(current_time)
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] KeyboardInterrupt caught...")
        shutdown = True
    finally:        
        shutdown = True
        executor.shutdown(wait=True, cancel_futures=False)
        print("[SHUTDOWN] All agent tasks completed")
        #area_state_manager.stop_listener()
        client.close()
        print("[SHUTDOWN] All connections closed")
        agent_state_manager.reset_agents()
        area_state_manager.reset_area()
        print("[SHUTDOWN] Complete")

if __name__ == "__main__":
    main()
