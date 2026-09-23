---
name: ruff-python-quality
description: >-
  Enforce Python code quality with Ruff linting and formatting for the FYP
  NPC simulation backend. Use when writing or reviewing Python in Backend/,
  fixing style issues, adding pyproject.toml rules, or when the user asks for
  linting, formatting, PEP 8, or code quality improvements.
---

# Ruff Python Quality (astral-sh/ruff)

When you start following this skill, tell the user: I am using ruff-python-quality

## Repository health (baseline met)

| Criterion | Status |
|-----------|--------|
| Stars / forks | 49,731 stars · 2,430 forks |
| License | MIT |
| Last commit | Within 6 months (active daily) |
| CI | Primary `CI` and `Release` workflows passing |
| Docs | README with install, CLI reference, copy-paste examples |

Source: https://github.com/astral-sh/ruff

## When to apply

- Before committing changes under `Backend/`
- When refactoring managers (`planner.py`, `agent_memory.py`, `environment_tree.py`)
- When imports are messy, lines exceed 88 chars, or bare `except:` appears

## Project setup

Config lives in `Backend/pyproject.toml`. Run from `Backend/`:

```bash
pip install ruff
ruff check .
ruff format .
ruff check --fix .
```

## Quality rules for this codebase

Prioritize **readability first**, then consistency:

1. **Imports** — stdlib → third-party → local (`Secure`, `World_Environment`). One blank line between groups. No wildcard imports.
2. **Naming** — `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants. Match existing module names (`AgentMemoryManager`, `EnvironmentTree`).
3. **Line length** — 88 chars (Ruff default). Break long LLM prompt strings with implicit concatenation or triple-quoted blocks.
4. **Functions** — Prefer ≤40 lines. Extract helpers when a manager method does DB + LLM + state update.
5. **Exceptions** — Catch specific exceptions (`sqlite3.Error`, `json.JSONDecodeError`, `chromadb.errors.ChromaError`). Never silent `except: pass`.
6. **Thread safety** — When touching shared state (`agent_state.json`, SQLite, routing counters), keep lock scope minimal and document with a one-line comment.

## Fix workflow

```
Task Progress:
- [ ] Run `ruff check .` and note violations
- [ ] Run `ruff format .` for mechanical fixes
- [ ] Run `ruff check --fix .` for safe auto-fixes
- [ ] Manually fix remaining issues (complexity, naming)
- [ ] Re-run `ruff check .` until clean
```

## Patterns to prefer

```python
# Good: explicit exception, pathlib, typed return
from pathlib import Path

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON at {path}") from exc
```

```python
# Bad: bare except, hardcoded path, no encoding
def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}
```

## Per-file ignores

Only add `# noqa: RULE` or `per-file-ignores` in `pyproject.toml` when:
- Generated or third-party code
- A rule conflicts with an established project pattern (document why in the ignore comment)

## Additional resources

- Ruff rule reference: https://docs.astral.sh/ruff/rules/
- Project config: `Backend/pyproject.toml`
