---
name: langgraph-agents
description: >-
  Build and extend LangGraph agent workflows for the FYP NPC simulation.
  Use when editing execute_plan.py, StateGraph nodes, tool routing, checkpointing,
  RunnableConfig, or multi-agent conversation flows in Backend/.
---

# LangGraph Agents (langchain-ai/langgraph)

When you start following this skill, tell the user: I am using langgraph-agents

## Repository health (baseline met)

| Criterion | Status |
|-----------|--------|
| Stars / forks | 42,141 stars · 7,123 forks |
| License | MIT |
| Last commit | Within 6 months (daily activity) |
| CI | Active workflows; large monorepo with frequent PR merges |
| Docs | README, tutorials, minimal graph examples |

Source: https://github.com/langchain-ai/langgraph

## When to apply

- Changes to `execute_plan.py` graph construction
- Adding tools, nodes, or conditional edges for agent dialogue
- Passing per-agent config (`user_id`, `agent_name`, `agent_persona`) through `RunnableConfig`
- Debugging message state or checkpoint behavior

## Current project usage

`execute_plan.py` already uses:

- `StateGraph`, `START`, `END`
- `add_messages` reducer on `State`
- `ToolNode`, `tools_condition` (commented tool examples)
- `InMemorySaver`, `InMemoryStore`
- `RunnableConfig` with `configurable` dict for agent context

## Graph design rules (quality + readability)

1. **Small nodes** — Each node does one thing: load memory, call LLM, persist result.
2. **Explicit state** — Keep `State` TypedDict minimal; add fields only when multiple nodes need them.
3. **Config for per-agent data** — Pass `user_id`, `agent_name`, `partner_id` via `config["configurable"]`, not global variables.
4. **No hidden side effects** — DB writes and Unity calls belong in named nodes or tools, not inside the LLM wrapper.
5. **Compile once** — Build and `compile()` the graph at module load; reuse across thread-pool tasks.

## Canonical patterns

### State definition

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
```

### Node with RunnableConfig

```python
from langchain_core.runnables import RunnableConfig

def agent_node(state: State, config: RunnableConfig) -> dict:
    conf = config.get("configurable", {})
    user_id: str = conf["user_id"]
    agent_name: str = conf["agent_name"]
    # Build prompt from memory_context + user_msgs
    response = dialogue_llm.invoke(messages)
    return {"messages": [response]}
```

### Graph assembly

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(State)
builder.add_node("agent", agent_node)
builder.add_edge(START, "agent")
builder.add_edge("agent", END)
graph = builder.compile(checkpointer=InMemorySaver())
```

### Invocation with per-agent config

```python
config = {
    "configurable": {
        "thread_id": f"{user_id}-{session_id}",
        "user_id": user_id,
        "agent_name": agent_name,
        "agent_persona": persona,
        "agent_tone": tone,
    }
}
result = graph.invoke({"messages": [{"role": "user", "content": query}]}, config)
```

## Integration with simulation loop

- **Thread pool** — `execute_plan.py` runs agents concurrently; each invocation must use a unique `thread_id` in config to avoid checkpoint collisions.
- **Memory context** — Load Chroma/SQLite context in the node before LLM call; do not store large blobs in `State.messages`.
- **Token budget** — Trim `user_msgs` and memory snippets before invoke; log counts via `Secure/request_counter.json`.

## Anti-patterns in this codebase

| Avoid | Prefer |
|-------|--------|
| Global `agent_state_manager` inside nodes without config | Pass IDs via `RunnableConfig` |
| Mixing Unity I/O in graph nodes | Keep graph for LLM dialogue only |
| Giant monolithic `agent_node` | Split: `load_context` → `call_llm` → `save_memory` |

## Additional resources

- LangGraph docs: https://langchain-ai.github.io/langgraph/
- Project entry point: `Backend/execute_plan.py`
