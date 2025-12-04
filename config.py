import os

from dotenv import load_dotenv

load_dotenv(r".env")

CONSUMER_KEY = os.environ["CONSUMER_KEY"]
CONSUMER_SECRET = os.environ["CONSUMER_SECRET"]
REQUEST_TOKEN_URL = os.environ["REQUEST_TOKEN_URL"]
ACCESS_TOKEN_URL = os.environ["ACCESS_TOKEN_URL"]
AUTHORIZE_URL = os.environ["AUTHORIZE_URL"]
CAMPAIGN_ID = os.environ["CAMPAIGN_ID"]
QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_COLLECTION_NAME = os.environ["QDRANT_COLLECTION_NAME"]
OLLAMA_URL = os.environ["OLLAMA_URL"]
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
OPENROUTER_URL = os.environ["OPENROUTER_URL"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GROQ_API_URL = os.environ["GROQ_API_URL"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

VECTOR_NAME = "fast-all-minilm-l6-v2"
