"""Stepwise executor: the deterministic cage around the plan.

Runs a plan one step at a time. For each step it resolves ``{"$ref": ...}``
inputs from earlier outputs, calls the tool through the registry (which
validates input and output schemas), and applies guardrails:

  * step budget — refuse plans/iterations beyond ``max_steps``;
  * retry-or-halt — retry transient tool errors up to ``max_attempts``, but halt
    immediately on a schema-validation failure or a disallowed tool (retrying a
    deterministic failure is pointless);
  * human checkpoint — a ``consequential`` step pauses (AWAITING_CHECKPOINT)
    unless an approval is supplied; this is the seam Phase 4 makes interactive.

Every guardrail decision is surfaced as an explicit event (returned and, when
persisting, written to the events table). Nothing is silently passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app import store
from app.planner import Plan
from app.registry import (
    SchemaValidationError,
    ToolNotAllowed,
    ToolRegistry,
)

_REF = re.compile(r"step(\d+)\.(\w+)")


class RunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    HALTED = "halted"
    AWAITING_CHECKPOINT = "awaiting_checkpoint"
    FAILED = "failed"


class StepStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    HALTED = "halted"
    AWAITING_CHECKPOINT = "awaiting_checkpoint"
    REJECTED = "rejected"


# Event kinds — the vocabulary of the audit trace.
class Event:
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    RETRY = "retry"
    VALIDATION_FAILURE = "validation_failure"
    DISALLOWED_TOOL = "disallowed_tool"
    UNRESOLVED_REF = "unresolved_ref"
    TOOL_ERROR = "tool_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    HUMAN_DECISION = "human_decision"
    REJECTED = "rejected"
    RUN_COMPLETED = "run_completed"


class RefError(Exception):
    """A $ref input could not be resolved from prior outputs."""


@dataclass
class GuardrailEvent:
    kind: str
    message: str
    step_index: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    index: int
    tool: str
    status: str
    attempts: int = 0
    inputs: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class RunResult:
    run_id: str
    status: str
    steps: list[StepResult]
    events: list[GuardrailEvent]
    outputs: dict[int, dict[str, Any]]

    @property
    def final_output(self) -> dict[str, Any] | None:
        return self.outputs[max(self.outputs)] if self.outputs else None


def _resolve(value: Any, outputs: dict[int, dict[str, Any]]) -> Any:
    """Recursively resolve {"$ref": "stepN.field"} against prior step outputs."""
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return _resolve_ref(value["$ref"], outputs)
        return {k: _resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, outputs) for v in value]
    return value


def _resolve_ref(ref: str, outputs: dict[int, dict[str, Any]]) -> Any:
    match = _REF.fullmatch(ref)
    if not match:
        raise RefError(f"Malformed reference: {ref!r}")
    idx, key = int(match.group(1)), match.group(2)
    if idx not in outputs:
        raise RefError(f"Reference to step{idx} but it has produced no output")
    if key not in outputs[idx]:
        raise RefError(f"step{idx} output has no field '{key}'")
    return outputs[idx][key]


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_steps: int = 10,
        max_attempts: int = 2,
        persist: bool = True,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self.max_attempts = max_attempts
        self.persist = persist

    # -- persistence helpers (no-ops when persist=False) -------------------- #

    def _event(
        self, run_id: str, events: list[GuardrailEvent], kind: str, message: str,
        *, step_index: int | None = None, data: dict | None = None,
    ) -> None:
        events.append(GuardrailEvent(kind, message, step_index, data or {}))
        if self.persist:
            store.record_event(
                run_id, kind, message, step_index=step_index, data=data
            )

    def _status(self, run_id: str, status: str) -> None:
        if self.persist:
            store.set_run_status(run_id, status)

    def _step(self, run_id: str, sr: StepResult) -> None:
        if self.persist:
            store.record_step(
                run_id, sr.index, sr.tool, sr.status, attempts=sr.attempts,
                inputs=sr.inputs, output=sr.output, error=sr.error,
            )

    # -- main loop ---------------------------------------------------------- #

    def run(
        self, run_id: str, plan: Plan, approvals: dict[int, bool] | None = None,
        prior_outputs: dict[int, dict[str, Any]] | None = None,
    ) -> RunResult:
        approvals = approvals or {}
        events: list[GuardrailEvent] = []
        steps: list[StepResult] = []
        # Resume support: outputs from already-completed steps are carried in.
        outputs: dict[int, dict[str, Any]] = dict(prior_outputs or {})
        completed = set(outputs)

        self._status(run_id, RunStatus.RUNNING)

        if len(plan.steps) > self.max_steps:
            self._event(
                run_id, events, Event.BUDGET_EXCEEDED,
                f"Plan has {len(plan.steps)} steps, over budget of {self.max_steps}.",
            )
            self._status(run_id, RunStatus.HALTED)
            return RunResult(run_id, RunStatus.HALTED, steps, events, outputs)

        for iteration, step in enumerate(plan.steps, start=1):
            if step.index in completed:  # already ran in a prior segment — carry forward
                steps.append(StepResult(
                    step.index, step.tool, StepStatus.SUCCEEDED,
                    output=outputs[step.index],
                ))
                continue

            if iteration > self.max_steps:  # iteration budget backstop
                self._event(
                    run_id, events, Event.BUDGET_EXCEEDED,
                    f"Iteration budget {self.max_steps} exhausted.", step_index=step.index,
                )
                self._status(run_id, RunStatus.HALTED)
                return RunResult(run_id, RunStatus.HALTED, steps, events, outputs)

            sr = StepResult(index=step.index, tool=step.tool, status=StepStatus.PENDING)

            # Human checkpoint for consequential steps.
            if step.consequential and approvals.get(step.index) is not True:
                if approvals.get(step.index) is False:
                    sr.status = StepStatus.REJECTED
                    steps.append(sr)
                    self._step(run_id, sr)
                    self._event(
                        run_id, events, Event.REJECTED,
                        f"Step {step.index} ({step.tool}) was rejected; run halted.",
                        step_index=step.index,
                    )
                    self._status(run_id, RunStatus.HALTED)
                    return RunResult(run_id, RunStatus.HALTED, steps, events, outputs)

                sr.status = StepStatus.AWAITING_CHECKPOINT
                sr.inputs = step.inputs
                steps.append(sr)
                self._step(run_id, sr)
                self._event(
                    run_id, events, Event.CHECKPOINT_REQUIRED,
                    f"Step {step.index} ({step.tool}) is consequential and needs approval.",
                    step_index=step.index,
                )
                self._status(run_id, RunStatus.AWAITING_CHECKPOINT)
                return RunResult(
                    run_id, RunStatus.AWAITING_CHECKPOINT, steps, events, outputs
                )

            # Resolve inputs from prior outputs.
            try:
                resolved = _resolve(step.inputs, outputs)
            except RefError as exc:
                sr.status = StepStatus.FAILED
                sr.error = str(exc)
                steps.append(sr)
                self._step(run_id, sr)
                self._event(
                    run_id, events, Event.UNRESOLVED_REF, str(exc), step_index=step.index
                )
                self._status(run_id, RunStatus.FAILED)
                return RunResult(run_id, RunStatus.FAILED, steps, events, outputs)

            sr.inputs = resolved
            self._event(
                run_id, events, Event.STEP_STARTED,
                f"Running step {step.index}: {step.tool}.", step_index=step.index,
            )
            sr.status = StepStatus.RUNNING
            self._step(run_id, sr)  # stamp start time for duration

            # Execute with retry-or-halt.
            halted = self._execute_step(run_id, step, resolved, sr, outputs, events)
            steps.append(sr)
            self._step(run_id, sr)
            if halted:
                self._status(run_id, RunStatus.FAILED)
                return RunResult(run_id, RunStatus.FAILED, steps, events, outputs)

        self._status(run_id, RunStatus.COMPLETED)
        self._event(run_id, events, Event.RUN_COMPLETED, "Run completed successfully.")
        return RunResult(run_id, RunStatus.COMPLETED, steps, events, outputs)

    def _execute_step(
        self, run_id: str, step, resolved: dict, sr: StepResult,
        outputs: dict[int, dict[str, Any]], events: list[GuardrailEvent],
    ) -> bool:
        """Run one step with retries. Returns True if the run must halt."""
        for attempt in range(1, self.max_attempts + 1):
            sr.attempts = attempt
            try:
                output = self.registry.call(step.tool, resolved)
            except ToolNotAllowed as exc:
                sr.status, sr.error = StepStatus.FAILED, str(exc)
                self._event(
                    run_id, events, Event.DISALLOWED_TOOL, str(exc), step_index=step.index
                )
                return True  # terminal — never retry a disallowed tool
            except SchemaValidationError as exc:
                sr.status, sr.error = StepStatus.FAILED, str(exc)
                self._event(
                    run_id, events, Event.VALIDATION_FAILURE, str(exc),
                    step_index=step.index, data={"direction": exc.direction},
                )
                return True  # deterministic failure — retry won't help
            except Exception as exc:  # noqa: BLE001 — transient tool error
                if attempt < self.max_attempts:
                    self._event(
                        run_id, events, Event.RETRY,
                        f"Step {step.index} failed (attempt {attempt}): {exc}. Retrying.",
                        step_index=step.index,
                    )
                    continue
                sr.status, sr.error = StepStatus.FAILED, str(exc)
                self._event(
                    run_id, events, Event.TOOL_ERROR,
                    f"Step {step.index} failed after {attempt} attempts: {exc}.",
                    step_index=step.index,
                )
                return True
            else:
                outputs[step.index] = output
                sr.status, sr.output = StepStatus.SUCCEEDED, output
                self._event(
                    run_id, events, Event.STEP_SUCCEEDED,
                    f"Step {step.index} ({step.tool}) succeeded.", step_index=step.index,
                )
                return False
        return True  # unreachable
