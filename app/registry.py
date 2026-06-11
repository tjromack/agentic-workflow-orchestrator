"""MCP-style tool registry: the allowlist and the only legal call path.

A tool is reachable iff it has been registered here. Every call goes through
``ToolRegistry.call``, which enforces the allowlist and validates inputs and
outputs against the tool's declared JSON Schema. The planner is handed only
``registry.specs()`` — names + schemas, never the handlers — so it cannot
reference anything that is not registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator

JsonSchema = dict[str, Any]
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class RegistryError(Exception):
    """Base class for registry-level failures."""


class ToolNotAllowed(RegistryError):
    """Raised when a name is not in the registry (i.e. not allowlisted)."""


class SchemaValidationError(RegistryError):
    """Raised when a tool's input or output fails schema validation."""

    def __init__(self, tool: str, direction: str, messages: list[str]):
        self.tool = tool
        self.direction = direction  # "input" or "output"
        self.messages = messages
        joined = "; ".join(messages)
        super().__init__(f"{tool} {direction} failed validation: {joined}")


@dataclass(frozen=True)
class Tool:
    """A registered capability with typed input/output schemas.

    ``consequential`` marks steps that have real-world effect (e.g. publishing
    an artifact); the executor pauses these for human approval in Phase 4.
    """

    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    handler: ToolHandler
    consequential: bool = False

    def spec(self) -> dict[str, Any]:
        """Planner-facing description. Deliberately excludes the handler."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "consequential": self.consequential,
        }


def _validate(schema: JsonSchema, instance: Any, tool: str, direction: str) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        messages = [
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        ]
        raise SchemaValidationError(tool, direction, messages)


class ToolRegistry:
    """Holds registered tools. Registration is the allowlist."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise RegistryError(f"Tool already registered: {tool.name}")
        # Reject malformed schemas at registration, not at call time.
        Draft202012Validator.check_schema(tool.input_schema)
        Draft202012Validator.check_schema(tool.output_schema)
        self._tools[tool.name] = tool

    def is_allowed(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotAllowed(f"Tool not in registry/allowlist: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        """What the planner sees: the full allowlist, schemas only."""
        return [self._tools[n].spec() for n in self.names()]

    def call(self, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """The single guarded entry point for running any tool.

        Enforces, in order: allowlist membership, input-schema validation,
        execution, output-schema validation.
        """
        tool = self.get(name)  # raises ToolNotAllowed if unregistered
        _validate(tool.input_schema, inputs, name, "input")
        output = tool.handler(inputs)
        _validate(tool.output_schema, output, name, "output")
        return output


def build_registry() -> ToolRegistry:
    """Construct the registry populated with the demo tools (the allowlist)."""
    # Imported here to avoid a circular import (tools import nothing from us).
    from app.tools import retrieve, summarize, write_brief

    registry = ToolRegistry()
    for get_tool in (retrieve.get_tool, summarize.get_tool, write_brief.get_tool):
        registry.register(get_tool())
    return registry
