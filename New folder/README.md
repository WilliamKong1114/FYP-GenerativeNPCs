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

1. Create and activate a virtual environment
   - Windows PowerShell
     - `python -m venv .venv`
     - `.\.venv\Scripts\Activate.ps1`

2. Install Python dependencies
   - `pip install -r requirements.txt`

3. Configure credentials

   `Secure/llm_config.py` reads `GITHUB_TOKEN` from environment variables. Put it in `.env`.
   Example `.env`: `GITHUB_TOKEN=...`

## Running the simulation

1. Start Unity first
   The Python runtime connects to Unity at `127.0.0.1:5005`, so Unity should be listening on that port.

2. Run the main loop
   - `python execute_plan.py`

If Unity is not running or the port is blocked, the Python process will fail when it tries to connect.

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
