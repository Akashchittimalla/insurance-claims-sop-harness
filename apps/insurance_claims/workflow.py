from threading import RLock
from typing import Any, TypedDict
import logging
from time import perf_counter

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from zoneinfo import ZoneInfo
from pydantic import ValidationError

from .consent import ConsentPurpose, ConsentSimulator, SQLiteConsentRepository
from .database import (
    AccessDenied, SQLiteClaimRepository, SQLiteCustomerRepository, SQLiteKnowledgeRepository,
)
from .identity import CallerEligibility, IdentityFields, IdentitySubmission, IdentityVerification
from .policy import (
    TOOLS, ClaimSearchOutput, Decision, DenialOutput, DocumentsOutput, HandoffOutput,
    KnowledgeOutput, PaymentOutput, Policy, StatusOutput, VerificationOutput, workflow_state,
)
from .fixtures_loader import ClaimRecord, ConsentStatus
from .claim_processing import ClaimProcessing
from .handoff import HandoffStatus, MockHandoff
from .session import (
    Candidate, EmailStatus, Emotion, IdentityField, Intent, Model, SessionState, SessionStatus,
    SQLiteSessions, VerificationStatus, reduce_memory,
)
from .sop import Phase, SOPMachine, load_sop
from .tools import ClaimToolGateway


LOGGER = logging.getLogger(__name__)


class ToolResult(Model):
    decision: Decision
    output: Any = None


class TurnResult(Model):
    state: SessionState
    waiting_for: str


class Turn(TypedDict, total=False):
    state: SessionState
    candidate: Candidate
    collected: IdentitySubmission
    connection: Any
    waiting_for: str
    verification_decision: Decision
    tool_calls: int
    ambiguity_statuses: tuple[str, ...]
    verification_source: str | None


class FoundationWorkflow:
    def __init__(self, sessions: SQLiteSessions, settings):
        self.sessions = sessions
        self.settings = settings
        self.policy = Policy(SOPMachine(load_sop()), settings)
        self.verifier = IdentityVerification(SQLiteCustomerRepository(sessions.database),
                                             settings.min_verification_fields)
        self.claims = ClaimToolGateway(SQLiteClaimRepository(sessions.database))
        self.handoff = MockHandoff(sessions)
        self.processing = ClaimProcessing(SQLiteKnowledgeRepository(sessions.database),
                                          sessions.clock, ZoneInfo(settings.business_timezone))
        self.consent = ConsentSimulator(
            sessions, SQLiteKnowledgeRepository(sessions.database), SQLiteConsentRepository(),
            settings.consent_max_polls,
        )
        # Raw candidates are scoped to this process and cleared on expiry or disposition.
        self._candidates = {}
        self._turn_lock = RLock()
        graph = StateGraph(Turn)
        graph.add_node("memory", self._memory)
        graph.add_node("verify", self._verify)
        graph.add_node("resolve", self._resolve)
        graph.add_node("process", lambda _: {"waiting_for": "case_discussion"})
        graph.add_node("post_process", lambda _: {"waiting_for": "email_choice"})
        graph.add_node("persist", self._persist)
        graph.add_edge(START, "memory")
        graph.add_conditional_edges("memory", self._route)
        graph.add_conditional_edges("verify", self._route_after_verify)
        for node in ("resolve", "process", "post_process"):
            graph.add_edge(node, "persist")
        graph.add_edge("persist", END)
        self._graph = graph.compile()

    def run(self, session_id: str, token: str, candidate: Candidate) -> TurnResult:
        if not isinstance(candidate, Candidate):
            raise TypeError("Expected validated Candidate")
        turn, _ = self._run(session_id, token, candidate)
        return turn

    def _run(self, session_id, token, candidate, *, verify_tool=False):
        with self._turn_lock:
            cutoff = self.sessions.clock()
            self._candidates = {
                key: entry for key, entry in self._candidates.items() if entry[0] > cutoff
            }
            with self.sessions.transaction() as connection:
                state = self.sessions.load(connection, session_id, token)
                if verify_tool and not self.policy.authorize_action("verify_identity", state).allowed:
                    decision = self._authorize(connection, state, "verify_identity",
                                               candidate.identity_candidates)
                    return TurnResult(state=state, waiting_for=state.status.value), decision
                if state.status != SessionStatus.ACTIVE:
                    return TurnResult(state=state, waiting_for=state.status.value), None
                saved = self._candidates.get(session_id)
                result = self.invoke(connection, state, candidate,
                                     saved[1] if saved else IdentitySubmission())
            state = result["state"]
            if state.verification == VerificationStatus.PENDING and state.status == SessionStatus.ACTIVE:
                self._candidates[session_id] = (state.updated_at + self.sessions.ttl, result["collected"])
            else:
                self._candidates.pop(session_id, None)
            return TurnResult(state=state, waiting_for=result["waiting_for"]), result.get(
                "verification_decision"
            )

    def invoke(self, connection, state, candidate, collected, verification_source=None):
        with tracing_context(enabled=False):
            return self._graph.invoke(
                {"state": state, "candidate": candidate, "connection": connection,
                 "collected": collected, "tool_calls": 0, "verification_source": verification_source},
                config={"recursion_limit": 10},
            )

    def _memory(self, turn: Turn):
        state, candidate = turn["state"], turn["candidate"]
        recovery = state.recovery
        frustrated = candidate.emotion in {Emotion.ANGRY, Emotion.FRUSTRATED, Emotion.DISTRESSED}
        progressed = candidate.identity_candidates is not None or (
            candidate.intent_hint is not None and candidate.intent_hint != state.memory.intent
        ) or (
            candidate.claim_hints is not None and any(
                getattr(state.memory.claim_hints, key) != value
                for key, value in candidate.claim_hints.model_dump(exclude_unset=True).items()
            )
        )
        updates = {
            "frustration_count": (recovery.frustration_count + 1 if frustrated and not progressed
                                  else 0 if progressed else recovery.frustration_count),
            "total_scope_violations": recovery.total_scope_violations + int(candidate.out_of_scope),
            "total_refusals": recovery.total_refusals + int(candidate.refused_verification),
            "refused_fields": recovery.refused_fields | candidate.refused_fields,
            "dependency_failures": 0,
            "stalled_turns": 0 if progressed else recovery.stalled_turns + int(candidate.recovery_stalled),
            "emotion_intensity": candidate.emotion_intensity,
            "recent_emotions": (*recovery.recent_emotions[-4:], candidate.emotion or Emotion.NEUTRAL),
        }
        if (progressed or candidate.constructive and recovery.offer_reason == "scope_limit") and not candidate.refused_verification:
            if recovery.offer_reason in {"scope_limit", "repeated_refusal", "repeated_frustration", "dependency_failure", "recovery_limit"}:
                updates["offer_reason"] = None
            if not frustrated:
                updates["declined_reason"] = None
        updated = state.model_copy(update={
            "memory": reduce_memory(state.memory, candidate, state.version + 1, state.phase),
            "recovery": recovery.model_copy(update=updates),
            "emotion": candidate.emotion or state.emotion,
            "out_of_scope_count": (state.out_of_scope_count + 1 if candidate.out_of_scope
                                   else 0 if candidate.constructive else state.out_of_scope_count),
            "refusal_count": (
                state.refusal_count + 1 if candidate.refused_verification
                else 0 if candidate.identity_candidates is not None else state.refusal_count
            ) if state.phase == Phase.VERIFY_ID else state.refusal_count,
        })
        return {"state": updated}

    @staticmethod
    def _route(turn: Turn) -> str:
        if turn["state"].status != SessionStatus.ACTIVE:
            return "persist"
        return {
            Phase.VERIFY_ID: "verify", Phase.RESOLVE_INTENT: "resolve",
            Phase.PROCESS_CASE: "process", Phase.POST_PROCESS: "post_process",
        }[turn["state"].phase]

    @staticmethod
    def _route_after_verify(turn: Turn) -> str:
        return "resolve" if turn["state"].phase == Phase.RESOLVE_INTENT else "persist"

    def _transition(self, connection, state, target):
        result = self.policy.apply_transition(state, target)
        allowed = result.phase == target and result.phase != state.phase
        self.sessions.audit(connection, state, "phase_transition", action=target.value,
                            decision="allowed" if allowed else "denied",
                            reason="guards_satisfied" if allowed else "guards_unsatisfied")
        return result

    def _verify(self, turn: Turn):
        candidate = turn["candidate"].identity_candidates
        if candidate is None:
            return {"waiting_for": "identity"}
        connection, state = turn["connection"], turn["state"]
        decision = self._authorize(connection, state, "verify_identity", candidate)
        if not decision.allowed:
            return {"waiting_for": "identity", "verification_decision": decision}
        combined = turn["collected"].model_dump() | candidate.model_dump(exclude_none=True)
        source = turn.get("verification_source")
        if (source and combined["caller_role"] == "policyholder"
                and sum(combined[field] is not None for field in IdentityFields.model_fields)
                >= self.settings.min_verification_fields
                and not self.sessions.reserve_verification(
                    connection, source, self.settings.verification_window_seconds,
                    self.settings.verification_window_attempts,
                )):
            self.sessions.audit(connection, state, "verification_rate_limited", decision="denied")
            return {"waiting_for": "verification_rate_limited", "tool_calls": 1}
        started = perf_counter()
        state, collected = self._match_identity(connection, state, turn["collected"], candidate)
        LOGGER.info("authorized tool=%s latency_ms=%.3f", "verify_identity", (perf_counter() - started) * 1000)
        self.sessions.audit(connection, state, "tool_execution", action="verify_identity",
                            decision="allowed")
        return {"state": state, "collected": collected, "waiting_for": "identity",
                "verification_decision": decision, "tool_calls": 1}

    def _match_identity(self, connection, state, previous, candidate):
        collected, verified = self.verifier.submit(previous, candidate)
        eligibility = self.verifier.caller_eligibility(collected)
        fields = tuple(IdentityField(name) for name in IdentityFields.model_fields
                       if getattr(collected, name) is not None)
        self.sessions.audit(connection, state, "identity_captured")
        state = state.model_copy(update={
            "caller_role": collected.caller_role, "representative_status": eligibility,
            "identity_candidate_fields": fields,
        })
        if collected.caller_role == "representative":
            state = state.model_copy(update={"represented_party_id": self.verifier.represented_party(collected)})
            return self._handoff(connection, state, "representative_review"), IdentitySubmission()
        if (len(fields) >= self.settings.min_verification_fields
                and eligibility == CallerEligibility.POLICYHOLDER
                and candidate != IdentitySubmission()):
            self.sessions.audit(connection, state, "verification_attempted")
            if verified is None:
                attempts = state.verification_attempts + 1
                locked = attempts >= self.settings.max_verification_attempts
                state = state.model_copy(update={
                    "verification_attempts": attempts,
                    "verification": VerificationStatus.LOCKED if locked else VerificationStatus.PENDING,
                })
                self.sessions.audit(connection, state, "verification_failed", reason="identity_unconfirmed")
                if locked:
                    self.sessions.audit(connection, state, "verification_locked")
                    return self._handoff(connection, state, "verification_locked"), IdentitySubmission()
        if verified is not None:
            self.sessions.audit(connection, state, "verification_succeeded")
            state = state.model_copy(update={
                "verification": VerificationStatus.VERIFIED, "authorized_party_id": verified.party_id,
                "verified_caller_ref": verified.party_id,
                "matched_fields": frozenset(IdentityField(name) for name in verified.matched_fields),
                "identity_candidate_fields": (),
            })
            return self._transition(connection, state, Phase.RESOLVE_INTENT), IdentitySubmission()
        return state, collected

    def _resolve(self, turn: Turn):
        state, connection = turn["state"], turn["connection"]
        intent = state.memory.intent
        if intent is None or not intent.supported or turn["candidate"].out_of_scope:
            return {"waiting_for": "intent"}
        calls = turn["tool_calls"]
        updates = {"resolved_intent": intent}
        if intent.requires_claim:
            self.sessions.audit(connection, state, "claim_search_attempted")
            remaining = self.settings.max_tool_calls_per_turn - calls
            result = self._execute(connection, state, "search_customer_claims", state.memory.claim_hints,
                                   remaining=remaining)
            if not result.decision.allowed:
                return {"waiting_for": "claim"}
            calls += 1
            matches = result.output.cases
            if len(matches) != 1:
                self.sessions.audit(connection, state, "claim_resolution", decision="waiting",
                                    reason="ambiguous" if matches else "no_match")
                return {"waiting_for": "claim_clarification" if matches else "claim_not_found",
                        "ambiguity_statuses": tuple(sorted({case.status for case in matches})),
                        "tool_calls": calls}
            updates.update(resolved_case_id=matches[0].case_id, claim_ownership_validated=True)
            self.sessions.audit(connection, state, "claim_ownership_validated", decision="allowed")
            self.sessions.audit(connection, state, "claim_resolution", decision="allowed", reason="unique_match")
        state = self._transition(connection, state.model_copy(update=updates), Phase.PROCESS_CASE)
        return {"state": state, "waiting_for": "case_discussion", "tool_calls": calls}

    def _persist(self, turn: Turn):
        state = self.sessions.save(turn["connection"], turn["state"])
        turn["connection"].execute(
            "INSERT INTO conversation_messages VALUES (?, ?, ?)",
            (state.session_id, state.version, state.phase.value),
        )
        waiting = state.status.value if state.status != SessionStatus.ACTIVE else turn.get("waiting_for", "input")
        return {"state": state, "waiting_for": waiting}

    def _handoff(self, connection, state, reason):
        try:
            record = self.handoff.request(connection, state, reason)
        except (LookupError, TimeoutError):
            self.sessions.audit(connection, state, "handoff_failed", reason=reason)
            return state.model_copy(update={"status": SessionStatus.HANDOFF,
                                            "handoff_status": HandoffStatus.FAILED.value,
                                            "escalation_reason": reason,
                                            "identity_candidate_fields": ()})
        self.sessions.audit(connection, state, "handoff_requested", reason=reason)
        return state.model_copy(update={
            "status": SessionStatus.HANDOFF, "handoff_status": record.status.value,
            "handoff_id": record.handoff_id,
            "escalation_reason": reason, "identity_candidate_fields": (),
        })

    def update_handoff(self, connection, state, *, resume=False):
        if resume and (
            state.verification == VerificationStatus.LOCKED
            or state.escalation_reason in {"identity_revalidation", "representative_review"}
        ):
            self.sessions.audit(connection, state, "session_recovery_required", decision="denied",
                                reason="manual_identity_review")
            return state
        try:
            record = self.handoff.update(connection, state, cancel=resume) if state.handoff_id else None
        except (LookupError, TimeoutError):
            self.sessions.audit(connection, state, "handoff_failed")
            return self.sessions.save(connection, state.model_copy(update={"handoff_status": "failed"}))
        if resume:
            self.sessions.audit(connection, state, "session_resumed", decision="allowed")
            return self.sessions.save(connection, state.model_copy(update={
                "status": SessionStatus.ACTIVE, "handoff_status": "cancelled", "handoff_id": None,
                "escalation_reason": None,
                "recovery": state.recovery.model_copy(update={"offer_reason": None}),
            }))
        if record:
            self.sessions.audit(connection, state, "handoff_status", reason=record.status.value)
            return self.sessions.save(connection, state.model_copy(update={"handoff_status": record.status.value}))
        return state

    def _authorize(self, connection, state, name, arguments, remaining=1):
        decision = self.policy.authorize_action(name, state, remaining=remaining)
        if decision.allowed and hasattr(arguments, "case_id") and arguments.case_id:
            # Scope an exact lookup to the verified owner before exposing any details.
            try:
                self.claims.check_ownership(workflow_state(state), arguments.case_id)
            except AccessDenied:
                decision = self.policy.authorize_action(name, state, owns=False, remaining=remaining)
                self.sessions.audit(connection, state, "claim_ownership_validated", decision="denied",
                                    reason="ownership_required")
        action = name if name in TOOLS else "unknown_tool"
        event_id = self.sessions.audit(connection, state, "tool_authorization", action=action,
                                       decision="allowed" if decision.allowed else "denied",
                                       reason=decision.reason)
        return decision.model_copy(update={"audit_event_id": event_id})

    def _execute(self, connection, state, name, arguments, remaining=1):
        started = perf_counter()
        tool = TOOLS.get(name)
        try:
            parsed = tool.input.model_validate(arguments) if tool else None
        except ValidationError:
            event_id = self.sessions.audit(connection, state, "tool_authorization", action=name,
                                           decision="denied", reason="invalid_arguments")
            return ToolResult(decision=Decision(allowed=False, reason="invalid_arguments",
                                               phase=state.phase, audit_event_id=event_id))
        decision = self._authorize(connection, state, name, parsed, remaining)
        if not decision.allowed:
            return ToolResult(decision=decision)
        identity_state = workflow_state(state)
        try:
            if name == "search_customer_claims":
                records = self.claims.search_claims(identity_state, parsed)
                output = ClaimSearchOutput(cases=tuple(ClaimRecord.model_validate(row.details) for row in records))
            elif name == "get_consent_status":
                output = self.consent.update(connection, state, parsed.request_id, parsed.purpose)
                if (output.status == ConsentStatus.TIMED_OUT and not state.recovery.offer_reason
                        and state.recovery.declined_reason != "consent_timeout"):
                    recovery = state.recovery.model_copy(update={"offer_reason": "consent_timeout"})
                    self.sessions.save(connection, state.model_copy(update={"recovery": recovery}))
                    self.sessions.audit(connection, state, "human_assistance_offered", reason="consent_timeout")
            elif tool.owner:
                claim = ClaimRecord.model_validate(self.claims.get_claim(identity_state, parsed.case_id).details)
                output = self._claim_output(state, name, parsed, claim)
            else:
                raise LookupError("Operation needs a dedicated state reducer")
        except (LookupError, AccessDenied, TimeoutError, ValidationError) as error:
            reason = "dependency_failure" if isinstance(error, (TimeoutError, ValidationError)) else "resource_unavailable"
            event_id = self.sessions.audit(connection, state, "tool_execution", action=name,
                                           decision="denied", reason=reason)
            return ToolResult(decision=decision.model_copy(update={
                "allowed": False, "reason": reason, "audit_event_id": event_id,
            }))
        self.sessions.audit(connection, state, "tool_execution", action=name, decision="allowed")
        LOGGER.info("authorized tool=%s latency_ms=%.3f", name, (perf_counter() - started) * 1000)
        return ToolResult(decision=decision, output=tool.output.model_validate(output))

    def _claim_output(self, state, name, parsed, claim):
        if name == "get_claim_details":
            return claim
        if name == "get_claim_status":
            return StatusOutput(status=claim.status, summary=claim.summary)
        if name == "get_denial_reason":
            return DenialOutput(denial_reason=claim.denial_reason, appeal_deadline=claim.appeal_deadline)
        if name == "get_required_documents":
            return DocumentsOutput(documents_needed=claim.documents_needed)
        if name == "get_payment_details":
            return PaymentOutput.model_validate(claim.model_dump(include=set(PaymentOutput.model_fields)))
        if name == "get_appeal_information":
            return self.processing.deadline(claim)
        if name == "get_financial_field_definition":
            return KnowledgeOutput(source=f"claim_schema.{parsed.field}",
                                   text=self.processing.field_definition(parsed.field))
        guides = self.processing.get_guidelines()
        if name == "get_claim_followup_guidance":
            source, text = self.processing.followup(guides, claim, parsed.topic, {state.resolved_intent})
        else:
            source, text = self.processing.document_text(
                guides, claim.case_type, parsed.document, name == "get_document_alternatives",
            )
        return KnowledgeOutput(source=source, text=text)

    def execute_tool(self, session_id, token, name, arguments, *, remaining=1):
        # Verification enters through run() so candidate accumulation and transitions are atomic.
        if name == "verify_identity":
            try:
                submission = IdentitySubmission.model_validate(arguments)
            except ValidationError:
                with self.sessions.transaction() as connection:
                    state = self.sessions.load(connection, session_id, token)
                    return self._execute(connection, state, name, arguments, remaining)
            if remaining > 0:
                result, decision = self._run(session_id, token, Candidate(identity_candidates=submission),
                                             verify_tool=True)
                return ToolResult(decision=decision, output=(
                    VerificationOutput(status=result.state.verification) if decision.allowed else None
                ))
        with self.sessions.transaction() as connection:
            state = self.sessions.load(connection, session_id, token)
            if name == "request_human_transfer" and arguments == {}:
                decision = self._authorize(connection, state, name, Model(), remaining)
                if not decision.allowed:
                    return ToolResult(decision=decision)
                state = self._handoff(connection, state, "customer_requested")
                self.sessions.save(connection, state)
                self.sessions.audit(connection, state, "tool_execution", action=name,
                                    decision="allowed")
                self._candidates.pop(session_id, None)
                return ToolResult(decision=decision, output=HandoffOutput(status=state.handoff_status))
            return self._execute(connection, state, name, arguments, remaining)

    def start_consent(self, session_id, token, scenario: str):
        with self.sessions.transaction() as connection:
            state = self.sessions.load(connection, session_id, token)
            if state.status != SessionStatus.ACTIVE or not state.identity_verified:
                raise AccessDenied("Consent unavailable")
            return self.consent.create(connection, state, scenario, ConsentPurpose.SIMULATION, "demo")

    def finish_discussion(self, session_id, token):
        """Trusted application operation after a case discussion has been fulfilled."""
        with self.sessions.transaction() as connection:
            state = self.sessions.load(connection, session_id, token)
            return self.complete_discussion(connection, state)

    def complete_discussion(self, connection, state):
        if (state.phase != Phase.PROCESS_CASE or state.status != SessionStatus.ACTIVE
                or state.discussion.pending or state.discussion.pending_intents or state.discussion.pending_topics):
            return state
        state = state.model_copy(update={"discussion_complete": True})
        return self.sessions.save(connection, self._transition(connection, state, Phase.POST_PROCESS))

    def skip_email(self, session_id, token):
        """Record an explicit structured decline; no external delivery occurs."""
        with self.sessions.transaction() as connection:
            state = self.sessions.load(connection, session_id, token)
            if state.phase != Phase.POST_PROCESS or state.status != SessionStatus.ACTIVE:
                return state
            state = state.model_copy(update={"email_status": EmailStatus.DECLINED})
            if self.policy.evaluate_completion(state):
                state = state.model_copy(update={"status": SessionStatus.COMPLETED})
                connection.execute("INSERT INTO email_events VALUES (?, ?)",
                                   (state.session_id, state.email_status.value))
                self.sessions.audit(connection, state, "session_completed", reason="email_declined")
            return self.sessions.save(connection, state)
