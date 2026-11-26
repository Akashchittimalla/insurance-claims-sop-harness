from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict
import yaml

from .identity import IdentitySubmission, IdentityVerification, VerifiedIdentity


class Phase(str, Enum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"


@dataclass(frozen=True)
class WorkflowState:
    """Trusted server-side state. Only IdentitySubmission is accepted from extraction."""

    phase: Phase = Phase.VERIFY_ID
    collected: IdentitySubmission = IdentitySubmission()
    identity: VerifiedIdentity | None = None
    intent_resolved: bool = False
    case_processed: bool = False

    @property
    def identity_verified(self) -> bool:
        return isinstance(self.identity, VerifiedIdentity)


GUARDS: dict[str, Callable[[WorkflowState], bool]] = {
    "identity_verified": lambda state: state.identity_verified,
    "intent_resolved": lambda state: state.intent_resolved,
    "case_processed": lambda state: state.case_processed,
}
REQUIRED_TRANSITIONS = {
    Phase.VERIFY_ID: (Phase.RESOLVE_INTENT, "identity_verified"),
    Phase.RESOLVE_INTENT: (Phase.PROCESS_CASE, "intent_resolved"),
    Phase.PROCESS_CASE: (Phase.POST_PROCESS, "case_processed"),
}


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Phase
    target: Phase
    guards: tuple[str, ...]


class SOPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    transitions: tuple[Transition, ...]


def load_sop(path: Path | None = None) -> SOPConfig:
    path = path if path is not None else Path(__file__).with_name("sop.yaml")
    return SOPConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class SOPMachine:
    def __init__(self, config: SOPConfig):
        self._transitions = {transition.source: transition for transition in config.transitions}
        if len(config.transitions) != len(REQUIRED_TRANSITIONS) or (
            self._transitions.keys() != REQUIRED_TRANSITIONS.keys()
        ):
            raise ValueError("SOP must define exactly one transition for each nonterminal phase")
        for source, (target, required_guard) in REQUIRED_TRANSITIONS.items():
            transition = self._transitions[source]
            if transition.target != target or required_guard not in transition.guards:
                raise ValueError(f"Invalid transition for {source.value}")
            unknown = set(transition.guards) - GUARDS.keys()
            if unknown:
                raise ValueError(f"Unknown SOP guards: {sorted(unknown)}")

    def advance(self, state: WorkflowState) -> WorkflowState:
        transition = self._transitions.get(state.phase)
        if transition and state.identity_verified and all(
            GUARDS[name](state) for name in transition.guards
        ):
            return replace(state, phase=transition.target)
        return state

    def submit_identity(
        self, state: WorkflowState, turn: IdentitySubmission, verifier: IdentityVerification
    ) -> WorkflowState:
        if state.phase != Phase.VERIFY_ID:
            raise ValueError("Identity submission is only available during verification")
        collected, identity = verifier.submit(state.collected, turn)
        if identity is not None:
            collected = IdentitySubmission()
        return self.advance(replace(state, collected=collected, identity=identity))
