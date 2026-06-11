"""Phase 1 gate: tools are reachable only through the registry, with schema
validation on the way in and out."""

import pytest

from app.registry import (
    SchemaValidationError,
    Tool,
    ToolNotAllowed,
    ToolRegistry,
    build_registry,
)


def _echo_tool() -> Tool:
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    return Tool(
        name="echo",
        description="echo back value",
        input_schema=schema,
        output_schema=schema,
        handler=lambda inp: {"value": inp["value"]},
    )


def test_unregistered_tool_is_blocked():
    reg = ToolRegistry()
    assert reg.is_allowed("echo") is False
    with pytest.raises(ToolNotAllowed):
        reg.call("echo", {"value": "x"})


def test_input_validation_rejects_bad_payload():
    reg = ToolRegistry()
    reg.register(_echo_tool())
    with pytest.raises(SchemaValidationError) as exc:
        reg.call("echo", {"value": 123})  # not a string
    assert exc.value.direction == "input"


def test_output_validation_catches_misbehaving_tool():
    reg = ToolRegistry()
    bad = _echo_tool()
    object.__setattr__(bad, "handler", lambda inp: {"value": 42})  # wrong type
    reg.register(bad)
    with pytest.raises(SchemaValidationError) as exc:
        reg.call("echo", {"value": "ok"})
    assert exc.value.direction == "output"


def test_specs_expose_allowlist_without_handlers():
    reg = build_registry()
    names = {s["name"] for s in reg.specs()}
    assert names == {"retrieve_documents", "summarize_sources", "write_brief"}
    assert all("handler" not in spec for spec in reg.specs())
    consequential = {s["name"] for s in reg.specs() if s["consequential"]}
    assert consequential == {"write_brief"}


def test_demo_chain_runs_end_to_end():
    reg = build_registry()
    retrieved = reg.call("retrieve_documents", {"query": "green roofs stormwater", "k": 3})
    assert retrieved["documents"], "expected at least one matching document"

    summary = reg.call(
        "summarize_sources",
        {"question": "benefits of green roofs", "documents": retrieved["documents"]},
    )
    assert summary["outline"]

    brief = reg.call(
        "write_brief",
        {
            "question": "benefits of green roofs",
            "outline": summary["outline"],
            "documents": retrieved["documents"],
        },
    )
    assert brief["brief_markdown"].startswith("# ")
    assert brief["citations"]
