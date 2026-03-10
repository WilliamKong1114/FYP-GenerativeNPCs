import os
from dotenv import load_dotenv
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
#from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAI
#api_key = os.getenv("GOOGLE_API_KEY")

load_dotenv()
tokens_env = os.getenv("GITHUB_TOKEN")
ENDPOINT = "https://models.github.ai/inference"

def build_client_github(model_name: str, temperature: float, max_tokens: int = 4096):
    return AzureAIChatCompletionsModel(
        endpoint=ENDPOINT,
        credential=tokens_env,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=1.0, 
        timeout=10,
        max_retries=2
    )
""" 
def build_client_google(model_name: str, temperature: float, max_tokens: int = 4096):
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=max_tokens,
        top_p=1.0, 
        timeout=10,
        max_retries=2
    )
 """
 
#"meta/Meta-Llama-3.1-8B-Instruct"
#"cohere/cohere-command-a"

#dialogue_llm = build_client_github("openai/gpt-4.1-mini", 0.3)
#dialogue_llm = build_client_github("meta/Llama-3.2-11B-Vision-Instruct", 0.3)
dialogue_llm = build_client_github("openai/gpt-4o-mini", 0.3)
skill_llm = build_client_github("meta/Meta-Llama-3.1-8B-Instruct", 0.3)
planner_llm = build_client_github("openai/gpt-4o-mini", 0.3, 2048)
emoji_llm = build_client_github("meta/Meta-Llama-3.1-8B-Instruct", 0.3)
routing_llm = build_client_github("microsoft/Phi-4", 0.3)
observe_llm = build_client_github("mistral-ai/Ministral-3B", 0.7, 2048)
reflect_llm = build_client_github("openai/gpt-4.1-mini", 0.8, 4096)

#"gemini-1.5-pro"

#dialogue_llm = build_client_google("gemini-1.5-flash", 0.3)
#skill_llm = build_client_google("gemini-2.5-flash-lite", 0.3)
#planner_llm = build_client_google("gemini-1.5-flash", 0.3, 2048)
#routing_llm = build_client_google("gemini-1.5-flash", 0.3)