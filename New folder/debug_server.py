from flask import Flask, request, jsonify
from dotenv import load_dotenv
from World_Environment.simulation_clock import SimulationClock
from conversation_manager import ConversationManager
from execute_plan import get_graph
from World_Environment.area_state_manager import AreaSystem

load_dotenv()
app = Flask(__name__)
clock = SimulationClock(time_scale=90.0)
conv_manager = ConversationManager(graph=get_graph(), clock=clock, debug_mode=True)

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

    area_name = init_loc

    if init_loc != rec_loc:
        return jsonify({"status": "error", "message": f"Agents are in different areas: {init_loc} vs {rec_loc}. Conversation skipped."}), 400
    
    group = [
        {"id": initiator_id, "persona": agent_executions[initiator_id]["persona"]},
        {"id": receiver_id, "persona": agent_executions[receiver_id]["persona"]}
    ]

    dialogue_result = None
    if conv_manager.start_conversation(area_name, group):
        dialogue_result = conv_manager.handle_conversation(area_name, group, agent_executions)

    dialogue = dialogue_result if dialogue_result else "No conversation generated"
    
    return jsonify({
        "status": "success",
        "dialogue": dialogue,
        #"agent_executions": agent_executions,
    })
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)