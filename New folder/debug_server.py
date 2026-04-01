from flask import Flask, request, jsonify
from dotenv import load_dotenv
from World_Environment.simulation_clock import SimulationClock
from conversation_manager import ConversationManager
from execute_plan import get_graph
from World_Environment.area_state_manager import AreaSystem
from Interaction_manager import UserToAgentInteractManager

load_dotenv()
app = Flask(__name__)
clock = SimulationClock(time_scale=90.0)
conv_manager = ConversationManager(graph=get_graph(), clock=clock, debug_mode=True)
user_chat_manager = UserToAgentInteractManager()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ready", "mode": "debug"})

@app.route('/update_area', methods=['POST'])
def update_area():
    data = request.json or {}
    app.logger.info(f"Received data: {data}") 
    agent_id = data.get("agentName")
    area = data.get("areaName")
    status = data.get("status")
    
    if not all([agent_id, area, status]):
        return jsonify({"status": "error", "message": f"Missing fields: {agent_id, area, status}"}), 400
    
    AreaSystem.get_manager(area).set_agent_in_area(agent_id, area, status)
    
    return jsonify({"status": "success", "message": f"Updated {agent_id} location to {area} with status {status}"})

@app.route('/generate_conversation', methods=['POST'])
def generate_conversation():
    data = request.json or {}
    initiator_id = data.get("initiator")
    receiver_id = data.get("receiver")
    init_loc = data.get("initLoc")
    rec_loc = data.get("recLoc")
    session_id = data.get("session_id")
    
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
        },
        {
            "id": "Swithin Eldrede",
            "persona":("Timid, easily startled.",
            "Swithin Eldrede is a 46 year old villager who has lived his whole life in the small medieval settlement near the river, surrounded by pasturelands and the forest edge that both fascinates and terrifies him.",
            "He grew up in a family that gathered berries, herbs, and mushrooms, but his nervous temperament made him cautious of every rustling leaf and shifting shadow.",
            "He enjoys collecting herbs close to the village boundary, drying them carefully, weaving small grass charms to calm himself.",
            "His typical day involves checking his small garden, picking herbs near the safer paths, avoiding dense woods, and asking neighbors if they have seen anything unusual that he should know about.",
            "In the evenings, he sits close to the communal fire, clutching a warm cup of tea, listening anxiously to stories especially those he hopes does not keep him awake all night.")
        },
        {
            "id": "Beowulf Warwicke",
            "persona": ("Ordinary.",
            "Beowulf Warwicke is a 70 year old villager who has spent his entire life in a modest medieval settlement nestled between rolling pasturelands and a river. Behind the village lie dense woodlands where he often walks to gather herbs and fallen branches.",
            "He does not speak at all. Every day, he walks down to the riverside and simply sits there, doing nothing, watching the water flow. He remains until nightfall before quietly returning home. He repeats this routine without change, day after day.")
        }
    ]

    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "is_chatting": False,
            "is_reflecting": False,
            "active_task": None,
        } for config in agents_config
    }

    if init_loc != rec_loc:
        return jsonify({"status": "error", "message": f"Agents are in different areas: {init_loc} vs {rec_loc}. Conversation skipped."}), 400

    for agent_id in [initiator_id, receiver_id]:
        if agent_id not in agent_executions:
            return jsonify({"status": "error", "message": f"Unknown agent: {agent_id}"}), 400

    area_name = init_loc
    group = [
        {"id": initiator_id, "persona": agent_executions[initiator_id]["persona"]},
        {"id": receiver_id, "persona": agent_executions[receiver_id]["persona"]}
    ]

    dialogue_lines = conv_manager.handle_conversation(area_name, group, agent_executions=agent_executions, session_id=session_id)
    return jsonify({
        "status": "success",
        "dialogue": dialogue_lines or [],
    })


@app.route('/user-chat/starters', methods=['POST'])
def user_chat_starters():
    data = request.json or {}
    agent_id = data.get("agent_id")
    payload = user_chat_manager.get_starter_questions(agent_id=agent_id)
    return jsonify(payload)


@app.route('/user-chat/start', methods=['POST'])
def user_chat_start():
    data = request.json or {}
    agent_id = data.get("agent_id")
    starter_question_id = data.get("starter_question_id")
    starter_question_text = data.get("starter_question_text")

    try:
        payload = user_chat_manager.start_conversation(
            agent_id=agent_id,
            starter_question_id=starter_question_id,
            starter_question_text=starter_question_text,
        )
        return jsonify(payload)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/user-chat/choose', methods=['POST'])
def user_chat_choose():
    data = request.json or {}
    session_id = data.get("session_id")
    option_id = data.get("option_id")

    try:
        payload = user_chat_manager.choose_option(session_id=session_id, option_id=option_id)
        return jsonify(payload)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)