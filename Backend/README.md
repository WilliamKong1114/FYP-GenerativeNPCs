# AI-Driven NPC Simulation (Unity + Python)

This repository contains the Python side of a multi-agent simulation. LLM-driven villagers follow daily plans, move around within the environment, record observations and memories, and sometimes start conversations with each other or with the player.

Different modules are implemented for agents to corredinate with. There are a total of 6 agents in the current setup, and 7 modules including: Planning, Routing, Preference, Conversation, Commitment, Observation and Reflection. Each module collaborates with LLM models to achieve dynamic response optimization under different circumstances. The LLM models are accessed via the GitHub Models inference API.

## Key components

- Main script: `execute_plan.py`
- Unity TCP client: `unity_comm.py`
- Environment state and clock: `World_Environment/`
- Chroma vector database related: `chromaMemory_manager.py` & `chroma_db/`
- SQLite databases related: `Database/`
  - `plans.db` for storing generated plans
  - `agent_memory.db` for storing observations, impressions, conversation logs, summaries and reflections
  - `places.db` for visualizing the environment tree structure
  - `preferences.db` for storing agent preferences

## Requirements

- Windows/macOS/Linux
- Project build with Python 3.12 venv
- A Unity scene
- A GitHub Models token available as `GITHUB_TOKEN`

## Setup

1. Create and activate a virtual environment with python version of 3.12.0
   - Windows PowerShell
   - `python -m venv .venv`
   - `.\.venv\Scripts\Activate.ps1`

2. Install Python dependencies
   - `pip install -r requirements.txt`

3. Configure credentials
   - `Secure/llm_config.py` reads `GITHUB_TOKEN` from environment variables. Put it in `.env`.
     Example `.env`: `GITHUB_TOKEN=...`

   - Go to the github account settings, then Developer settings -> Personal access tokens -> Tokens (classic) to generate a token.
     `https://github.com/settings/tokens`

## Running the simulation

1. Run the Unity Scene FIRST

2. Run the main loop
   - `python execute_plan.py`

## !!! Caution !!!

- The observations function has now been turned on due to huge token consumption. It is suggested to turn it on for a few steps just for testing. Since running for a case of 5 agents will cause a total of 5 \* 33 = 165 API callings. And GitHub's maximum request per day is 150 per model.
- To turn it on, go to line 191 and uncomment the cline. `#record_observation(agent_id, area_name, obj_name, action, area_state_manager=area_state_manager, memory_manager=memory_manager, clock=clock)`

## Configuring agents

Agent personas, tone guidance, and home locations live in `World_Environment/agent_state.json`.
Typical fields per agent:

- `persona`: background and personality description for the agent, used for LLM prompting
- `tone`: relationship-based tone instructions
- `home_area` and `home_node`: where the agent resets to

## Data and persistence

- Chroma database and SQLite databases are included in the repo. If you want to reset the data, clear the data correspondingly.
- `chromaMemory_manager.py` can be used to clear specific collections.
- use sql command to delete records from specific tables.
