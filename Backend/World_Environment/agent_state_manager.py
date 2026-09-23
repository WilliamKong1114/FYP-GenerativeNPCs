import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from World_Environment.agent_state_schema import AgentProfile, AgentStateFile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "agent_state.json")
SIM_TIME_FILE = os.path.join(BASE_DIR, "simulationTime.json")


class AgentStateManager:
    """Loads agent_state.json as read-only configuration.

    Runtime action text stays in memory. The JSON file is never written.
    """

    def __init__(
        self, file_path: str = STATE_FILE, time_file: str = SIM_TIME_FILE
    ) -> None:
        self.state_file = file_path
        self.time_file = time_file
        self._state = self._load_state()
        self.simulation_time: dict[str, str] = {"time": ""}
        self.load_simulation_time(self._state.time)

    def get_agent_state(self) -> dict[str, dict[str, Any]]:
        return {
            agent_id: profile.model_dump()
            for agent_id, profile in self._state.agents.items()
        }

    def set_agent_state(self, agent_id: str, action_desc: str) -> None:
        profile = self._require_agent(agent_id)
        profile.action = action_desc

    def _load_state(self) -> AgentStateFile:
        path = Path(self.state_file)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Cannot read agent state file: {path}") from exc
        if not content.strip():
            raise ValueError(f"Agent state file is empty: {path}")
        try:
            return AgentStateFile.model_validate_json(content)
        except ValidationError as exc:
            raise ValueError(f"Invalid agent state file: {path}: {exc}") from exc

    def load_simulation_time(self, fallback_time: str = "") -> None:
        if os.path.exists(self.time_file):
            try:
                with open(self.time_file, encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        loaded = json.loads(content)
                        if isinstance(loaded, dict):
                            time_value = loaded.get("time", "")
                            self.simulation_time["time"] = str(time_value)
                            return
            except (OSError, json.JSONDecodeError, TypeError):
                pass

        if fallback_time:
            self.simulation_time["time"] = fallback_time
        self._save_simulation_time()

    def _save_simulation_time(self) -> None:
        with open(self.time_file, "w", encoding="utf-8") as f:
            json.dump(self.simulation_time, f, indent=4)

    def get_time(self) -> str:
        return self.simulation_time.get("time", "")

    def set_time(self, time_string: str) -> None:
        self.simulation_time["time"] = time_string
        self._save_simulation_time()

    def reset_agents(self) -> None:
        for agent_id, profile in self._state.agents.items():
            profile.action = f"{agent_id} is resting at home."

    def _require_agent(self, agent_id: str) -> AgentProfile:
        profile = self._state.agents.get(agent_id)
        if profile is None:
            raise KeyError(agent_id)
        return profile
