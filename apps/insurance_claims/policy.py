from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from .consent import ConsentPurpose, ConsentRequest
from .database import ClaimFilters
from .fixtures_loader import ClaimRecord
from .claim_processing import AppealInformation, Topic
from .identity import IdentitySubmission, VerifiedIdentity
from .session import EmailStatus, Intent, Model, SessionState, SessionStatus, VerificationStatus
from .sop import Phase, SOPMachine, WorkflowState


class CaseInput(Model):
    case_id: str


class ConsentInput(Model):
    request_id: str
    purpose: ConsentPurpose


class DenialOutput(Model):
    denial_reason: str | None
    appeal_deadline: date | None


class DocumentsOutput(Model):
    documents_needed: tuple[str, ...] | None


class PaymentOutput(Model):
    expected_reimbursement_amount: Decimal | None
    allowed_max_amount: Decimal | None
    net_pay: Decimal | None
    net_fee: Decimal | None


class StatusOutput(Model):
    status: str
    summary: str


class DocumentInput(CaseInput):
    document: str


class FollowupInput(CaseInput):
    topic: Topic


class FieldInput(CaseInput):
    field: Literal["net_pay", "net_fee", "expected_reimbursement_amount", "allowed_max_amount"]


class KnowledgeOutput(Model):
    source: str
    text: str | None


class ClaimSearchOutput(Model):
    cases: tuple[ClaimRecord, ...]


class VerificationOutput(Model):
    status: VerificationStatus


class HandoffOutput(Model):
    status: str


@dataclass(frozen=True)
class Tool:
    input: type[BaseModel]
    output: type[BaseModel]
    phases: frozenset[Phase]
    verified: bool = True
    owner: bool = False
    consent: bool = False
    side_effect: bool = False


CLAIM_PHASES = frozenset({Phase.RESOLVE_INTENT, Phase.PROCESS_CASE, Phase.POST_PROCESS})
TOOLS = {
    "verify_identity": Tool(IdentitySubmission, VerificationOutput, frozenset({Phase.VERIFY_ID}), verified=False, side_effect=True),
    "search_customer_claims": Tool(ClaimFilters, ClaimSearchOutput, CLAIM_PHASES, owner=True),
    "get_claim_details": Tool(CaseInput, ClaimRecord, CLAIM_PHASES, owner=True),
    "get_denial_reason": Tool(CaseInput, DenialOutput, CLAIM_PHASES, owner=True),
    "get_required_documents": Tool(CaseInput, DocumentsOutput, CLAIM_PHASES, owner=True),
    "get_payment_details": Tool(CaseInput, PaymentOutput, CLAIM_PHASES, owner=True),
    "get_claim_status": Tool(CaseInput, StatusOutput, CLAIM_PHASES, owner=True),
    "get_financial_field_definition": Tool(FieldInput, KnowledgeOutput, CLAIM_PHASES, owner=True),
    "get_document_guidance": Tool(DocumentInput, KnowledgeOutput, CLAIM_PHASES, owner=True),
    "get_document_alternatives": Tool(DocumentInput, KnowledgeOutput, CLAIM_PHASES, owner=True),
    "get_claim_followup_guidance": Tool(FollowupInput, KnowledgeOutput, CLAIM_PHASES, owner=True),
    "get_appeal_information": Tool(CaseInput, AppealInformation, CLAIM_PHASES, owner=True),
    "get_consent_status": Tool(ConsentInput, ConsentRequest, CLAIM_PHASES, side_effect=True),
    "request_human_transfer": Tool(Model, HandoffOutput, frozenset(Phase), verified=False, side_effect=True),
    "send_email": Tool(Model, HandoffOutput, frozenset({Phase.POST_PROCESS}), consent=True, side_effect=True),
}


class Decision(Model):
    allowed: bool
    reason: str
    phase: Phase
    required_guards: tuple[str, ...] = ()
    audit_event_id: str | None = None


def workflow_state(state: SessionState) -> WorkflowState:
    identity = VerifiedIdentity(state.authorized_party_id) if state.identity_verified else None
    intent_ready = isinstance(state.resolved_intent, Intent) and state.resolved_intent.supported and (
        not state.resolved_intent.requires_claim
        or (state.resolved_case_id is not None and state.claim_ownership_validated)
    )
    return WorkflowState(phase=state.phase, identity=identity, intent_resolved=intent_ready,
                         case_processed=state.discussion_complete)


class Policy:
    def __init__(self, machine: SOPMachine, settings):
        self.machine = machine
        self.settings = settings

    def authorize_action(self, name: str, state: SessionState, *, owns=True, remaining=1) -> Decision:
        tool = TOOLS.get(name)
        reason = "allowed"
        if state.status != SessionStatus.ACTIVE:
            reason = "inactive_session"
        elif tool is None:
            reason = "unknown_tool"
        elif state.phase not in tool.phases:
            reason = "invalid_phase"
        elif tool.verified and not state.identity_verified:
            reason = "verification_required"
        elif name == "verify_identity" and state.verification == VerificationStatus.LOCKED:
            reason = "verification_locked"
        elif tool.owner and not owns:
            reason = "ownership_required"
        elif tool.consent and not state.email_consent_granted:
            reason = "explicit_consent_required"
        elif remaining <= 0:
            reason = "execution_limit"
        elif name == "send_email":
            reason = "tool_unavailable"
        guards = () if tool is None else tuple(
            key for key, enabled in (
                ("active_phase", True), ("verified_identity", tool.verified),
                ("owner_scope", tool.owner), ("explicit_consent", tool.consent),
            ) if enabled
        )
        return Decision(allowed=reason == "allowed", reason=reason, phase=state.phase, required_guards=guards)

    def get_allowed_actions(self, state):
        return tuple(name for name in TOOLS if self.authorize_action(name, state).allowed)

    def can_transition(self, state, target):
        if len(state.matched_fields) < self.settings.min_verification_fields:
            return False
        current = workflow_state(state)
        return (
            state.status == SessionStatus.ACTIVE and current.phase != target
            and self.machine.advance(current).phase == target
        )

    def apply_transition(self, state, target):
        return state.model_copy(update={"phase": target}) if self.can_transition(state, target) else state

    def evaluate_completion(self, state):
        return state.phase == Phase.POST_PROCESS and (
            state.email_status == EmailStatus.DECLINED
            or (state.email_consent_granted and state.email_status in {EmailStatus.SENT, EmailStatus.FAILED})
        )

    def evaluate_escalation(self, state):
        if state.verification == VerificationStatus.LOCKED:
            return "verification_locked"
        if state.caller_role == "representative":
            return "representative_review"
        if state.refusal_count >= self.settings.max_verification_refusals:
            return "repeated_refusal"
        if state.out_of_scope_count >= self.settings.max_out_of_scope_attempts:
            return "scope_limit"
        return None
