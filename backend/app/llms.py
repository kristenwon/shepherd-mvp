from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr
from langchain_huggingface import HuggingFaceEndpoint
# from kindoChat import KindoChat
import os
from dotenv import load_dotenv
load_dotenv()


def create_openai_embeddings():
    """Create OpenAI embeddings with automatic key rotation on quota errors"""
    from langchain_openai import OpenAIEmbeddings

    # Load API keys with their environment variable names
    api_keys = [
        ("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY")),
        ("OPENAI_API_KEY_2", os.getenv("OPENAI_API_KEY_2")),
    ]

    # Filter out None values but keep the names
    available_keys = [(name, key) for name, key in api_keys if key]

    if not available_keys:
        error_msg = "No OpenAI API keys found in environment variables"
        raise ValueError(error_msg)

    print(f"[MAS] Found {len(available_keys)} API key(s) for embeddings")

    # Try each API key
    for env_name, api_key in available_keys:
        try:
            print(f"[MAS] Attempting to create embeddings with {env_name}")

            # IMPORTANT: Override the environment variable
            os.environ["OPENAI_API_KEY"] = api_key

            embeddings = OpenAIEmbeddings(
                openai_api_key=api_key  # Explicitly pass the key
            )

            # Test the embeddings with a minimal request
            try:
                test_result = embeddings.embed_query("test")
                print(
                    f"[MAS] Successfully initialized embeddings with {env_name}")
                return embeddings

            except Exception as test_error:
                error_str = str(test_error)
                if any(x in error_str.lower() for x in ["401", "403", "insufficient_quota", "429", "exceeded your current quota", "incorrect api key", "invalid_api_key"]):
                    print(
                        f"[MAS] {env_name} failed for embeddings: {str(test_error)[:100]}...")
                    continue
                else:
                    print(
                        f"[MAS] Unexpected error with {env_name} for embeddings: {test_error}")
                    continue

        except Exception as e:
            print(
                f"[MAS] Failed to initialize embeddings with {env_name}: {e}")
            continue

    # If we get here, all keys failed
    error_msg = "All OpenAI API keys exhausted or invalid for embeddings"
    raise Exception(error_msg)
