from typing import List, Tuple
import requests

from qdrant_client import QdrantClient
from qdrant_client.models import SearchParams, Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

from config import OLLAMA_MODEL, OLLAMA_URL, QDRANT_COLLECTION_NAME, QDRANT_URL


# 1. Retrieval from Qdrant
def retrieve_context(
    question: str,
    limit: int = 5,
    include_gm_only: bool = False,
) -> Tuple[List[str], List[str]]:
    """
    Returns:
        contexts: list of chunk texts
        titles:   list of titles for the chunks
    """
    client = QdrantClient(url=QDRANT_URL)
    embed_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    q_vec = embed_model.encode(question).tolist()

    # Optional filters (right now just GM-only flag)
    must = []

    if not include_gm_only:
        must.append(
            FieldCondition(
                key="gm_only",
                match=MatchValue(value=False),
            )
        )

    query_filter = Filter(must=must) if must else None

    result = client.query_points(
        collection_name=QDRANT_COLLECTION_NAME,
        query=q_vec,  # vector
        limit=limit,
        with_payload=True,
        search_params=SearchParams(hnsw_ef=128),
        query_filter=query_filter,
    )

    contexts: List[str] = []
    titles: List[str] = []

    for point in result.points:
        payload = point.payload or {}
        text = payload.get("content")
        title = payload.get("title", "<no title>")

        if text:
            contexts.append(text)
            titles.append(title)

    return contexts, titles


# 2. Call Ollama
def call_ollama(system_prompt: str, user_prompt: str) -> str:
    prompt = f"""System: {system_prompt}

User: {user_prompt}
"""

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        },
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["response"].strip()


# 3. High-level ask() function
def ask(question: str, top_k: int = 5, include_gm_only: bool = False):
    contexts, titles = retrieve_context(
        question,
        limit=top_k,
        include_gm_only=include_gm_only,
    )

    if not contexts:
        return (
            "I couldn't find anything relevant in the campaign notes.",
            [],
        )

    context_block = "\n\n---\n\n".join(contexts)

    system_prompt = (
        "You are the lore keeper of a Dungeons & Dragons campaign. "
        "You must answer ONLY using the information provided in the context below. "
        "If the answer is not explicitly stated in the context, respond with 'I don't know based on the provided information.' "
        "Do NOT use any outside knowledge, do NOT guess, and do NOT make up information. "
        "Always base your answer strictly on the context."
    )

    user_prompt = f"""Context:\n{context_block}\n\nQuestion: {question}\n\nRemember: If the answer is not in the context, say 'I don't know based on the provided information.'\n\nAnswer in a concise, clear way, referring to PCs, NPCs, locations, and events by name when relevant."""

    answer = call_ollama(system_prompt, user_prompt)

    # unique titles
    unique_titles = sorted(set(titles))
    return answer, unique_titles


if __name__ == "__main__":
    while True:
        q = input("Enter your question (or 'exit' to quit): ").strip()
        if q.lower() == "exit":
            break

        answer, titles = ask(q, top_k=5)

        print(f"Q: {q}\n")
        print("Answer:")
        print(answer)
        print("\nSources:")
        for t in titles:
            print(f"- {t}")
