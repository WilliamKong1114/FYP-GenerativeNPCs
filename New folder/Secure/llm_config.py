import os
from dotenv import load_dotenv
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from openai import APITimeoutError

load_dotenv()

tokens_env = os.getenv("GITHUB_TOKEN")
ENDPOINT = "https://models.github.ai/inference"

def _build_client(model_name: str, temperature: float):
    return AzureAIChatCompletionsModel(
        endpoint=ENDPOINT,
        credential=tokens_env,
        model=model_name,
        temperature=temperature,
        max_tokens=4096,
        top_p=1.0, 
        timeout=20,
        max_retries=2,
    )

dialogue_llm = _build_client("meta/Meta-Llama-3.1-8B-Instruct", 0.3)
skill_llm = _build_client("openai/gpt-4.1-mini", 0.2)
planner_llm = _build_client("mistral-ai/Codestral-2501", 0.1)
routing_llm = _build_client("microsoft/Phi-4", 0.0)
#routing_llm = _build_client("cohere/cohere-command-a", 0.0)