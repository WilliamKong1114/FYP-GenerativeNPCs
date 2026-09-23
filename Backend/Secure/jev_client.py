import os
from typing import Any

import requests
from dotenv import load_dotenv
from langsmith import traceable

from Secure.request_counter import increment_request_counter

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

JEV_MODEL = "typesafe/jev-1.13"
JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
JEV_TIMEOUT_SECONDS = 10.0


def _extract_choice(payload: object, question_id: str) -> str | None:
    if not isinstance(payload, dict):
        return None

    answers = payload.get("answers")
    data = payload.get("data")
    if answers is None and isinstance(data, dict):
        answers = data.get("answers")
    if not isinstance(answers, dict):
        return None

    answer = answers.get(question_id)
    if isinstance(answer, str) and answer:
        return answer
    if isinstance(answer, dict):
        choice = answer.get("choice")
        if isinstance(choice, str) and choice:
            return choice
    return None


@traceable(
    name="jev_choice",
    run_type="llm",
    tags=["jev", "routing"],
    metadata={
        "ls_provider": "openrouter",
        "ls_model_name": JEV_MODEL,
    },
)
def jev_choice(
    state: dict[str, Any],
    question_id: str,
    instructions: str,
    criteria: dict[str, str],
    timeout: float = JEV_TIMEOUT_SECONDS,
) -> str | None:
    """Ask JEV to pick one key from criteria. Returns that key or None."""
    if len(criteria) < 2:
        return next(iter(criteria), None)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key.strip() in {".", "..."}:
        print("[JEV] OPENROUTER_API_KEY is missing or still a placeholder.")
        return None

    increment_request_counter(JEV_MODEL)
    try:
        response = requests.post(
            JEV_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": JEV_MODEL,
                "state": state,
                "questions": {
                    question_id: {
                        "type": "choice",
                        "instructions": instructions,
                        "criteria": criteria,
                    }
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"[JEV] Request failed: {exc}")
        return None
    except ValueError as exc:
        print(f"[JEV] Invalid JSON response: {exc}")
        return None

    choice = _extract_choice(payload, question_id)
    if choice is None:
        print(f"[JEV] No choice in response for '{question_id}': {payload}")
    return choice
