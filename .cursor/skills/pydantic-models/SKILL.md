---
name: pydantic-models
description: >-
  Model agent state, plans, and API payloads with Pydantic for validation and
  readable schemas in the FYP NPC simulation. Use when parsing JSON configs,
  validating agent_state.json, structuring LLM outputs, or replacing ad-hoc
  dict access in Backend/.
---

# Pydantic Models (pydantic/pydantic)

When you start following this skill, tell the user: I am using pydantic-models

## Repository health (baseline met)

| Criterion | Status |
|-----------|--------|
| Stars / forks | 28,846 stars · 2,979 forks |
| License | MIT |
| Last commit | Within 6 months |
| CI | `CI` workflow passing |
| Docs | README, migration guide, copy-paste model examples |

Source: https://github.com/pydantic/pydantic

## When to apply

- Loading `World_Environment/agent_state.json`, `action_config.json`, plan JSON from SQLite
- Validating LLM-generated plan steps before `parse_plan()` executes them
- Replacing `json.loads` + manual `.get()` chains in managers
- Defining request/response shapes for Flask debug endpoints

## Install

```bash
pip install pydantic
```

Add to `requirements.txt` when adopted in production code paths.

## Design principles (readability-first)

1. **One model per domain concept** — `AgentProfile`, `PlanStep`, `AreaAction`, not one mega-model.
2. **Field descriptions** — Use `Field(description=...)` for fields that appear in LLM prompts or docs.
3. **Validate at load time** — Parse JSON files once at startup; fail fast with clear errors.
4. **Keep models flat** — Nest only when the JSON is genuinely hierarchical (agent → persona list).
5. **Separate IO from logic** — Models live in a `schemas/` or `models/` module; managers call `.model_validate()`.

## Project mapping

### Agent state (`agent_state.json`)

```python
from pydantic import BaseModel, Field

class AgentProfile(BaseModel):
    persona: list[str]
    tone: list[str]
    home_node: str
    home_area: str
    action: str = "idle"

class AgentStateFile(BaseModel):
    agents: dict[str, AgentProfile]

# Usage in AgentStateManager
state = AgentStateFile.model_validate_json(path.read_text(encoding="utf-8"))
wilton = state.agents["Wilton"]
```

### Plan steps (from `planner.py` / `plans.db`)

```python
class PlanStep(BaseModel):
    time: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    action: str = Field(min_length=1)

class DailyPlan(BaseModel):
    description: str
    emojis: list[str] = []
    steps: list[PlanStep] = []
```

Validate LLM output **before** writing to SQLite or executing.

### Chroma metadata

```python
class MemoryMetadata(BaseModel):
    type: str
    user_id: str
    created_at: str
    auto_created: bool = False
```

## LLM output validation pattern

```python
from pydantic import ValidationError

try:
    plan = DailyPlan.model_validate_json(llm_response)
except ValidationError as exc:
    # Log structured errors; retry or fall back to safe default
    raise ValueError(f"Invalid plan from LLM: {exc}") from exc
```

## Migration strategy

Do not rewrite all managers at once:

1. Add models for the highest-churn JSON (agent state, plans).
2. Replace `json.loads` in one manager; run simulation smoke test.
3. Extend to observation/reflection payloads when those modules change.

## Additional resources

- Pydantic v2 docs: https://docs.pydantic.dev/latest/
- See also: `mypy-type-checking` skill for annotating model methods
