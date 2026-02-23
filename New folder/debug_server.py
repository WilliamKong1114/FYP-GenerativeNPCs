from flask import Flask, request, jsonify
from dotenv import load_dotenv
from World_Environment.simulation_clock import SimulationClock
from conversation_manager import ConversationManager
from execute_plan import get_graph

load_dotenv()
app = Flask(__name__)
clock = SimulationClock(time_scale=90.0)
convo_manager = ConversationManager(graph=get_graph(), clock=clock, debug_mode=True)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ready", "mode": "debug"})

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

    current_agent_states = [{
        "id": initiator_id,
        "state": {"interaction_area" : init_loc},
        "persona": ""
    }, {
        "id": receiver_id,
        "state": {"interaction_area" : rec_loc},
        "persona": ""
    }]

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

    msg = convo_manager.trigger_group_chat(current_agent_states, agent_executions, client=None)

    return jsonify({
        "status": "success",
        "dialogue": msg,
        #"agent_executions": agent_executions,
    })
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)