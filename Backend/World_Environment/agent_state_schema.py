from pydantic import BaseModel, ConfigDict, Field


class AgentProfile(BaseModel):
    """Static villager profile loaded from agent_state.json."""

    model_config = ConfigDict(extra="forbid")

    persona: list[str] = Field(description="Personality and background lines.")
    tone: list[str] = Field(description="Relationship tone guidelines.")
    home_node: str
    home_area: str
    action: str = "idle"
    role: str | None = None
    workplace: str | None = None


class AgentStateFile(BaseModel):
    """Read-only contents of agent_state.json."""

    model_config = ConfigDict(extra="forbid")

    agents: dict[str, AgentProfile]
    time: str = ""
