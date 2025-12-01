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

VECTOR_NAME = "fast-all-minilm-l6-v2"
