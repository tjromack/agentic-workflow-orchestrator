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

# Function words + research-instruction noise. Filtering these keeps retrieval on
# the content terms of a goal ("urban green roofs") rather than matching on "write
# a brief on the…", and lets a genuinely off-corpus query return zero documents.
_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "is", "are",
    "be", "with", "about", "into", "from", "as", "at", "by", "this", "that",
    "write", "writing", "brief", "summarize", "summary", "research", "report",
    "short", "current", "state", "give", "me", "please", "produce", "draft",
    "overview", "note", "create",
}

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
    query_terms = {t for t in _tokens(inputs["query"]) if t not in _STOPWORDS}
    k = inputs.get("k", 5)
    if not query_terms:  # nothing meaningful to search for
        return {"documents": []}

    scored: list[tuple[float, dict[str, Any]]] = []
    for doc in _load_corpus():
        haystack = set(_tokens(f"{doc['title']} {doc['text']} {doc['topic']}"))
        matched = query_terms & haystack
        if not matched:
            continue
        score = len(matched) / len(query_terms)  # fraction of the query covered
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
