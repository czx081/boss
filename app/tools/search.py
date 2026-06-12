from typing import Dict, List


DOCUMENTS: List[Dict[str, str]] = [
    {
        "title": "Minimal Agent Runtime",
        "content": "A minimal agent repeatedly asks an LLM whether to answer or call a tool.",
    },
    {
        "title": "Session Memory",
        "content": "Session memory stores conversation history and durable task state across turns.",
    },
    {
        "title": "Tool Safety",
        "content": "Tool calls should validate arguments, catch exceptions, and record execution traces.",
    },
    {
        "title": "Maximum Steps",
        "content": "A maximum step limit prevents an agent from entering an infinite tool-use loop.",
    },
]


def search(query: str, limit: int = 3) -> dict:
    words = [word.lower() for word in query.split() if word.strip()]
    scored = []
    for document in DOCUMENTS:
        text = (document["title"] + " " + document["content"]).lower()
        score = sum(text.count(word) for word in words)
        if score:
            scored.append((score, document))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = [item[1] for item in scored[: max(1, min(limit, 5))]]
    return {"query": query, "results": results}

