import os
from dotenv import load_dotenv
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from openai import APITimeoutError

load_dotenv()

tokens_env = os.getenv("GITHUB_TOKEN")
ENDPOINT = "https://models.github.ai/inference"

def _build_client(model_name: str, temperature: float, max_tokens: int = 4096):
    return AzureAIChatCompletionsModel(
        endpoint=ENDPOINT,
        credential=tokens_env,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=1.0, 
        timeout=10,
        max_retries=2,
    )

#dialogue_llm = _build_client("openai/gpt-4.1-mini", 0.5)
dialogue_llm = _build_client("meta/Meta-Llama-3.1-8B-Instruct", 0.3)

#skill_llm = _build_client("meta/Meta-Llama-3.1-8B-Instruct", 0.3)
skill_llm = _build_client("openai/gpt-4.1-mini", 0.3)
#skill_llm = _build_client("openai/gpt-4.1-nano", 0.3)

planner_llm = _build_client("openai/gpt-4o-mini", 0.3, 2048)

#routing_llm = _build_client("meta/Meta-Llama-3.1-8B-Instruct", 0.3)
routing_llm = _build_client("microsoft/Phi-4", 0.3)
#routing_llm = _build_client("cohere/cohere-command-a", 0.3)