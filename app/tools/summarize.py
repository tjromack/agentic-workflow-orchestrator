"""summarize_sources — turn retrieved documents into a cited outline.

Deterministic stub: builds one outline section per document, splitting its
snippet into points and attaching the document id as the citation. This keeps
the demo runnable with no API key. An LLM-backed implementation can replace
``_handler`` once the provider abstraction lands in Phase 2; the schema is the
contract either way.
"""

from __future__ import annotations

import re
from typing import Any

from app.registry import Tool

_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Each retrieved document carries these fields (see retrieve_documents output).
_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "source": {"type": "string"},
        "url": {"type": "string"},
        "snippet": {"type": "string"},
        "score": {"type": "number"},
    },
    "required": ["id", "title", "snippet"],
}

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "minLength": 1},
        "documents": {"type": "array", "items": _DOCUMENT_SCHEMA, "minItems": 1},
    },
    "required": ["question", "documents"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "outline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "string"}},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "points", "source_ids"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "key_findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["outline", "key_findings"],
    "additionalProperties": False,
}


def _points(snippet: str, limit: int = 3) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE.split(snippet) if s.strip()]
    return sentences[:limit]


def _handler(inputs: dict[str, Any]) -> dict[str, Any]:
    outline = []
    key_findings = []
    for doc in inputs["documents"]:
        points = _points(doc["snippet"])
        outline.append(
            {
                "heading": doc["title"],
                "points": points,
                "source_ids": [doc["id"]],
            }
        )
        if points:
            key_findings.append(f"{points[0]} [{doc['id']}]")

    return {"outline": outline, "key_findings": key_findings}


def get_tool() -> Tool:
    return Tool(
        name="summarize_sources",
        description=(
            "Synthesize retrieved documents into an inspectable outline "
            "(headings, points, and the source ids each point came from) plus "
            "a list of key findings. Operates only on the documents passed in."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        handler=_handler,
        consequential=False,
    )
