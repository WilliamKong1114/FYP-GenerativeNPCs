import os
import json
import threading
from datetime import datetime
from dotenv import load_dotenv
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel

load_dotenv()
tokens_env = os.getenv("GITHUB_TOKEN")
ENDPOINT = "https://models.github.ai/inference"

COUNTER_FILE = os.path.join(os.path.dirname(__file__), "request_counter.json")
counter_lock = threading.Lock()

def increment_request_counter(model_name: str):
    today = datetime.now().strftime("%Y-%m-%d")
    data = {"date": today, "models": {}}
    with counter_lock:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r") as f:
                data = json.load(f)

        if data.get("date") != today:
            data["date"] = today
            for model in data["models"]:
                data["models"][model] = 0

        if model_name not in data["models"]:
            data["models"][model_name] = 0

        data["models"][model_name] += 1

        with open(COUNTER_FILE, "w") as file:
            json.dump(data, file, indent=4)
        return data["models"][model_name]
    
class AzureAIWithCounter(AzureAIChatCompletionsModel):
    def invoke(self, *args, **kwargs):
        count = increment_request_counter(self.model_name)
        #print(f"--- Request Count for {self.model_name} today: {count} ---")
        return super().invoke(*args, **kwargs)

def build_client_github(model_name: str, temperature: float, max_tokens: int = 4096):
    return AzureAIWithCounter(
        endpoint=ENDPOINT,
        credential=tokens_env,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=1.0, 
        timeout=10,
        #max_retries=2
    )

#
#mistral-ai/Codestral-2501 | code generation
#meta/Meta-Llama-3.1-8B-Instruct | img recognition 
#cohere/cohere-command-a
#cohere/Cohere-command-r-08-2024 | code generation
#
reflect_llm = build_client_github("mistral-ai/Ministral-3B", 0.5)
dialogue_llm = build_client_github("openai/gpt-4.1-nano", 0.8, 4096)
planner_llm = build_client_github("mistral-ai/mistral-medium-2505", 0.7, 4096)
conversation_llm = build_client_github("openai/gpt-4o-mini", 0.5, 4096)
observe_llm = build_client_github("meta/Meta-Llama-3.1-8B-Instruct", 0.8, 2048)
routing_llm = build_client_github("meta/Llama-3.2-11B-Vision-Instruct", 0.3, 2048)
impression_llm = build_client_github("microsoft/Phi-4", 0.8, 4096)
commitment_llm = build_client_github("openai/gpt-4.1-mini", 0.8, 4096)

if __name__ == "__main__":
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                data = json.load(f)
                for model, count in data["models"].items():
                    print(f"- {model}: {count}")
        except Exception as e:
            print(f"Error reading counter file: {e}")
    else:
        print("No counter file found.")
