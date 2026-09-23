import json
import os
import threading
from datetime import datetime

COUNTER_FILE = os.path.join(os.path.dirname(__file__), "request_counter.json")
counter_lock = threading.Lock()


def increment_request_counter(model_name: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    data: dict[str, object] = {"date": today, "models": {}}
    with counter_lock:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE) as f:
                data = json.load(f)

        if data.get("date") != today:
            data["date"] = today
            models = data.get("models")
            if isinstance(models, dict):
                for model in models:
                    models[model] = 0

        models = data.setdefault("models", {})
        if not isinstance(models, dict):
            models = {}
            data["models"] = models

        if model_name not in models:
            models[model_name] = 0

        models[model_name] = int(models[model_name]) + 1

        with open(COUNTER_FILE, "w") as file:
            json.dump(data, file, indent=4)
        return int(models[model_name])
