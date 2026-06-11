"""write_brief — assemble an approved outline into a cited markdown brief.

Flagged ``consequential``: it produces the final artifact, so the executor
pauses for human approval (Phase 4) before it runs. Deterministic stub now;
swappable for an LLM implementation later behind the same schema.
"""

from __future__ import annotations

from typing import Any

from app.registry import Tool

_OUTLINE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "heading": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
        "source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["heading", "points", "source_ids"],
}

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
    "required": ["id", "source", "url"],
}

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "minLength": 1},
        "outline": {"type": "array", "items": _OUTLINE_ITEM_SCHEMA, "minItems": 1},
        "documents": {"type": "array", "items": _DOCUMENT_SCHEMA, "minItems": 1},
    },
    "required": ["question", "outline", "documents"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "brief_markdown": {"type": "string", "minLength": 1},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "source": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["id", "source", "url"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["brief_markdown", "citations"],
    "additionalProperties": False,
}


def _handler(inputs: dict[str, Any]) -> dict[str, Any]:
    docs_by_id = {d["id"]: d for d in inputs["documents"]}

    lines = [f"# {inputs['question']}", ""]
    cited_ids: list[str] = []
    for section in inputs["outline"]:
        refs = "".join(f" [{sid}]" for sid in section["source_ids"])
        lines.append(f"## {section['heading']}{refs}")
        for point in section["points"]:
            lines.append(f"- {point}")
        lines.append("")
        for sid in section["source_ids"]:
            if sid not in cited_ids:
                cited_ids.append(sid)

    lines.append("## Sources")
    citations = []
    for sid in cited_ids:
        doc = docs_by_id.get(sid)
        if doc is None:
            continue  # cite only sources actually provided
        lines.append(f"- [{sid}] {doc['source']} — {doc['url']}")
        citations.append({"id": sid, "source": doc["source"], "url": doc["url"]})

    return {"brief_markdown": "\n".join(lines).strip() + "\n", "citations": citations}


def get_tool() -> Tool:
    return Tool(
        name="write_brief",
        description=(
            "Assemble an approved outline and its source documents into a cited "
            "markdown brief. Consequential: produces the final artifact and is "
            "gated behind a human checkpoint."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        handler=_handler,
        consequential=True,
    )
