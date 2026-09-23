---
name: mypy-type-checking
description: >-
  Add static type hints and mypy checks to improve readability and catch bugs
  in the FYP NPC simulation backend. Use when adding type annotations, fixing
  mypy errors, typing LLM responses, SQLite helpers, or threading code in
  Backend/.
---

# Mypy Type Checking (python/mypy)

When you start following this skill, tell the user: I am using mypy-type-checking

## Repository health (baseline met)

| Criterion | Status |
|-----------|--------|
| Stars / forks | 20,648 stars · 3,310 forks |
| License | MIT (see repo LICENSE file) |
| Last commit | Within 6 months |
| CI | `Tests` workflow passing on recent runs |
| Docs | README, cheat sheet, extensive typing docs |

Source: https://github.com/python/mypy

## When to apply

- New modules or public functions in `Backend/`
- Refactoring managers that pass `dict` blobs between planner, memory, and environment
- Thread-pool code in `execute_plan.py` and `environment_tree.py`
- Before merging changes that touch SQLite or Chroma return types

## Project setup

Config in `Backend/pyproject.toml`. Run from `Backend/`:

```bash
pip install mypy
mypy .
```

Start strict on **new code**; tighten existing modules incrementally.

## Typing priorities (readability-first)

1. **Function signatures** — Always annotate parameters and return types on public functions.
2. **Domain aliases** — Use `TypeAlias` for repeated shapes:

```python
from typing import TypeAlias

AgentId: TypeAlias = str
PlanStep: TypeAlias = tuple[str, str]  # (time, action)
```

3. **Optional vs required** — Use `str | None` (Python 3.12 style), not bare `Optional` unless matching legacy code.
4. **JSON boundaries** — Parse into typed structures at the boundary; avoid `dict[str, Any]` deep in business logic.
5. **SQLite rows** — Return `list[tuple[...]]` or small `@dataclass` records instead of untyped tuples.
6. **Threading** — Annotate shared structures (`Dict[str, EnvironmentNode]`, locks) so lock scope is obvious.

## Project-specific patterns

### Environment tree

```python
def find_node(self, name: str) -> EnvironmentNode | None: ...
def build_area_list(self, root: EnvironmentNode) -> list[str]: ...
```

### Agent memory

```python
def get_recent_conversation_logs(
    self, user_id: str, limit: int = 5
) -> list[tuple[str, str, str, str]]: ...
```

Prefer migrating these to a `@dataclass ConversationLog` when refactoring.

### LangGraph state (see `langgraph-agents` skill)

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
```

## Fix workflow

```
- [ ] Add types to new/changed function signatures
- [ ] Run `mypy .` from Backend/
- [ ] Fix errors bottom-up (helpers before callers)
- [ ] Use `cast()` only at untyped third-party boundaries
- [ ] Add `# type: ignore[code]` only with a one-line reason
```

## Common mypy fixes

| Error | Fix |
|-------|-----|
| `Item "None" has no attribute` | Guard with `if x is None: return` or assert |
| `Incompatible return value` | Narrow with `isinstance` or explicit branch |
| `Need type annotation for` | Add annotation at assignment |
| Missing stubs for `chromadb` | `ignore_missing_imports = true` in pyproject (already set) |

## Additional resources

- Mypy cheat sheet: https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html
- Project config: `Backend/pyproject.toml`
