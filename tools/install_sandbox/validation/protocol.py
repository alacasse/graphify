"""Validation-owned closed action and Raw Fact protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .catalog import InstallSurface, Scope


@dataclass(frozen=True, slots=True)
class ActionId:
    plan_id: str
    ordinal: int


class SurfaceExpectation(StrEnum):
    INSTALLED = "installed"
    ABSENT = "absent"


class PhaseKind(StrEnum):
    """The closed lifecycle and aggregate phases carried across the boundary."""

    INSTALL = "install"
    REINSTALL = "reinstall"
    REPAIR = "repair"
    TARGET_UNINSTALL = "target-uninstall"
    AGGREGATE_PREPARE = "aggregate-prepare"
    AGGREGATE_UNINSTALL = "aggregate-uninstall"


@dataclass(frozen=True, slots=True)
class TargetSubject:
    name: str


@dataclass(frozen=True, slots=True)
class AggregateSubject:
    preparation_targets: tuple[str, ...]


type ActionSubject = TargetSubject | AggregateSubject


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """Ask the Sandbox Runtime to invoke one planned product command."""

    action_id: ActionId
    subject: ActionSubject
    scope: Scope
    phase: PhaseKind
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    """Ask the Sandbox Runtime to observe planned Install Surfaces."""

    action_id: ActionId
    subject: ActionSubject
    scope: Scope
    phase: PhaseKind
    surfaces: tuple[InstallSurface, ...]
    expectation: SurfaceExpectation


type ActionRequest = CommandRequest | ObservationRequest


@dataclass(frozen=True, slots=True)
class CommandFact:
    """The minimal command fact needed by this planning slice."""

    action_id: ActionId
    exit_code: int


@dataclass(frozen=True, slots=True)
class ObservationFact:
    """The minimal observation fact needed by this planning slice."""

    action_id: ActionId
    matched: bool


type RawFact = CommandFact | ObservationFact
type Fulfil = Callable[[ActionRequest], RawFact]
