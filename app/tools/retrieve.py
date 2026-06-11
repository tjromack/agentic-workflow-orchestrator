"""retrieve_documents — keyword search over a local synthetic corpus.

Deterministic and offline: scores corpus documents by query-term overlap and
returns the top k. No live web calls, so demos are repeatable.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app.paths import CORPUS_DIR
from app.registry import Tool

_WORD = re.compile(r"[a-z0-9]+")

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "k": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["query"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "url": {"type": "string"},
                    "snippet": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["id", "title", "source", "url", "snippet", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["documents"],
    "additionalProperties": False,
}


@lru_cache(maxsize=1)
def _load_corpus() -> list[dict[str, Any]]:
    with (CORPUS_DIR / "documents.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _snippet(text: str, limit: int = 280) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _handler(inputs: dict[str, Any]) -> dict[str, Any]:
    query_terms = set(_tokens(inputs["query"]))
    k = inputs.get("k", 5)

    scored: list[tuple[float, dict[str, Any]]] = []
    for doc in _load_corpus():
        haystack = _tokens(f"{doc['title']} {doc['text']} {doc['topic']}")
        overlap = sum(1 for t in haystack if t in query_terms)
        if overlap == 0:
            continue
        score = overlap / len(haystack)  # length-normalized term frequency
        scored.append((score, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    documents = [
        {
            "id": doc["id"],
            "title": doc["title"],
            "source": doc["source"],
            "url": doc["url"],
            "snippet": _snippet(doc["text"]),
            "score": round(score, 4),
        }
        for score, doc in scored[:k]
    ]
    return {"documents": documents}


def get_tool() -> Tool:
    return Tool(
        name="retrieve_documents",
        description=(
            "Search a local synthetic corpus and return the top-k most relevant "
            "documents (id, title, source, url, snippet) for a query."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        handler=_handler,
        consequential=False,
    )
