from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import secrets
from typing import Annotated, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .database import ClaimFilters, SQLiteDatabase
from .identity import CallerEligibility, CallerRelationship, IdentitySubmission
from .sop import Phase


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    HANDOFF = "handoff"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    LOCKED = "locked"


class IdentityField(str, Enum):
    FULL_NAME = "full_name"
    DOB = "date_of_birth"
    PHONE = "phone"
    EMAIL = "email"
    SSN = "ssn_last4"


class Intent(str, Enum):
    CLAIM_STATUS = "CLAIM_STATUS"
    CLAIM_DENIAL = "CLAIM_DENIAL"
    CLAIM_PAYMENT = "CLAIM_PAYMENT"
    CLAIM_DOCUMENTS = "CLAIM_DOCUMENTS"
    CLAIM_APPEAL = "CLAIM_APPEAL"
    GENERAL_GUIDANCE = "GENERAL_GUIDANCE"
    CLAIM_DELAY = "CLAIM_DELAY"
    APPEAL_GUIDANCE = "APPEAL_GUIDANCE"
    DOCUMENT_REQUIREMENTS = "DOCUMENT_REQUIREMENTS"
    DOCUMENT_SUBMISSION = "DOCUMENT_SUBMISSION"
    DOCUMENT_ALTERNATIVES = "DOCUMENT_ALTERNATIVES"
    COVERAGE_INQUIRY = "COVERAGE_INQUIRY"
    CLAIM_SUBMISSION_GUIDANCE = "CLAIM_SUBMISSION_GUIDANCE"
    GENERAL_CLAIM_QUESTION = "GENERAL_CLAIM_QUESTION"
    HUMAN_TRANSFER = "HUMAN_TRANSFER"
    UNKNOWN = "UNKNOWN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"

    @property
    def supported(self) -> bool:
        return self not in {Intent.HUMAN_TRANSFER, Intent.UNKNOWN, Intent.OUT_OF_SCOPE}

    @property
    def requires_claim(self) -> bool:
        return self not in {Intent.GENERAL_GUIDANCE, Intent.CLAIM_SUBMISSION_GUIDANCE, Intent.COVERAGE_INQUIRY}


class EmailStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    DECLINED = "declined"
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"
    CONFUSED = "confused"
    ANXIOUS = "anxious"
    DISTRESSED = "distressed"


class ClaimHints(ClaimFilters):
    case_type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")] | None = None
    status: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")] | None = None
    case_id: Annotated[str, StringConstraints(pattern=r"^CL-[0-9]{1,12}$")] | None = None


class Candidate(Model):
    identity_candidates: IdentitySubmission | None = None
    policy_number_hint: Annotated[str, StringConstraints(pattern=r"^POL-[0-9]{1,12}$")] | None = None
    intent_hint: Intent | None = None
    secondary_intents: tuple[Intent, ...] = ()
    claim_hints: ClaimHints | None = None
    emotion: Emotion | None = None
    refused_verification: bool = False
    out_of_scope: bool = False
    constructive: bool = False
    emotion_intensity: Annotated[int, Field(ge=0, le=5)] = 0
    refused_fields: frozenset[IdentityField] = frozenset()
    recovery_stalled: bool = False


class Memory(Model):
    intent: Intent | None = None
    secondary_intents: tuple[Intent, ...] = ()
    claim_hints: ClaimFilters = ClaimFilters()
    policy_number: str | None = None
    provenance: dict[str, int] = Field(default_factory=dict)
    origin_phases: dict[str, Phase] = Field(default_factory=dict)


def reduce_memory(memory: Memory, candidate: Candidate, turn: int, phase: Phase | None = None) -> Memory:
    updates = {"secondary_intents": candidate.secondary_intents} if (
        "secondary_intents" in candidate.model_fields_set
    ) else {}
    for source, target in (("intent_hint", "intent"), ("policy_number_hint", "policy_number")):
        if source in candidate.model_fields_set:
            updates[target] = getattr(candidate, source)
    provenance = memory.provenance.copy()
    provenance.update(dict.fromkeys(updates, turn))
    if candidate.claim_hints is not None:
        hints = candidate.claim_hints.model_dump(exclude_unset=True)
        updates["claim_hints"] = memory.claim_hints.model_copy(update=hints)
        provenance.update(dict.fromkeys((f"claim_hints.{name}" for name in hints), turn))
    origins = memory.origin_phases.copy()
    if phase is not None:
        origins.update({key: phase for key, revision in provenance.items() if revision == turn})
    return memory.model_copy(update={**updates, "provenance": provenance, "origin_phases": origins})


class Discussion(Model):
    case_id: str | None = None
    document: str | None = None
    financial_field: str | None = None
    pending: tuple[str, ...] = ()
    pending_intents: tuple[Intent, ...] = ()
    pending_topics: tuple[str, ...] = ()
    pending_filters: ClaimFilters | None = None
    completed_topics: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    guidance_presented: tuple[str, ...] = ()
    manual_review_recommended: bool = False


class RecoveryState(Model):
    frustration_count: int = 0
    emotion_intensity: int = 0
    recent_emotions: tuple[Emotion, ...] = ()
    total_refusals: int = 0
    total_scope_violations: int = 0
    refused_fields: frozenset[IdentityField] = frozenset()
    dependency_failures: int = 0
    stalled_turns: int = 0
    offer_reason: str | None = None
    declined_reason: str | None = None
    steps: tuple[str, ...] = ()


class SessionState(Model):
    session_id: str
    phase: Phase = Phase.VERIFY_ID
    status: SessionStatus = SessionStatus.ACTIVE
    version: int = 0
    created_at: datetime
    updated_at: datetime
    verification: VerificationStatus = VerificationStatus.PENDING
    identity_candidate_fields: tuple[IdentityField, ...] = ()
    matched_fields: frozenset[IdentityField] = frozenset()
    verification_attempts: int = 0
    verified_caller_ref: str | None = None
    authorized_party_id: str | None = None
    caller_role: CallerRelationship | None = None
    representative_status: CallerEligibility = CallerEligibility.UNCONFIRMED
    represented_party_id: str | None = None
    representative_consent_ref: str | None = None
    memory: Memory = Memory()
    resolved_intent: Intent | None = None
    resolved_case_id: str | None = None
    discussion: Discussion = Discussion()
    claim_ownership_validated: bool = False
    refusal_count: int = 0
    out_of_scope_count: int = 0
    emotion: Emotion | None = None
    escalation_reason: str | None = None
    handoff_status: str | None = None
    handoff_id: str | None = None
    recovery: RecoveryState = RecoveryState()
    discussion_complete: bool = False
    email_consent_granted: bool = False
    email_status: EmailStatus = EmailStatus.NOT_REQUESTED
    authorized_recipient_ref: str | None = None
    summary_ref: str | None = None

    @property
    def identity_verified(self) -> bool:
        return self.verification == VerificationStatus.VERIFIED and self.authorized_party_id is not None


class AuditEvent(Model):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    timestamp: datetime
    event_type: str
    phase: Phase
    action: str | None = None
    decision: str | None = None
    reason: str | None = None


class SessionRepository(Protocol):
    def create(self) -> tuple[SessionState, str]: ...
    def get(self, session_id: str, token: str) -> SessionState: ...


class AuditRepository(Protocol):
    def audit_events(self, session_id: str) -> list[AuditEvent]: ...


class SessionUnavailable(LookupError):
    pass


SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    sequence INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    event TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consent_requests (
    request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoff_events (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id), reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoff_requests (
    handoff_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    record TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_windows (
    subject TEXT NOT NULL, window INTEGER NOT NULL, attempts INTEGER NOT NULL,
    PRIMARY KEY(subject, window)
);
CREATE TABLE IF NOT EXISTS recovery_metadata (
    name TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_messages (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    turn INTEGER NOT NULL,
    phase TEXT NOT NULL,
    PRIMARY KEY (session_id, turn)
);
CREATE TABLE IF NOT EXISTS email_events (
    session_id TEXT NOT NULL REFERENCES sessions(session_id), status TEXT NOT NULL,
    PRIMARY KEY (session_id, status)
);
CREATE TABLE IF NOT EXISTS summary_outcomes (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    preview TEXT NOT NULL,
    disposition TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_turns (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    message_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    safe_input TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (session_id, message_id)
);
"""


def now_utc():
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SQLiteSessions:
    def __init__(self, database: SQLiteDatabase, ttl_minutes: int, clock=now_utc):
        self.database = database
        self.clock = clock
        self.ttl = timedelta(minutes=ttl_minutes)

    def initialize(self):
        with closing(self.database.connect()) as connection:
            connection.executescript(SESSION_SCHEMA)
            with connection:
                connection.execute("INSERT OR IGNORE INTO recovery_metadata VALUES ('rate_salt', ?)",
                                   (secrets.token_hex(32),))

    def reserve_verification(self, connection, source: str, window_seconds: int, limit: int) -> bool:
        import hmac

        secret = connection.execute("SELECT value FROM recovery_metadata WHERE name = 'rate_salt'").fetchone()[0]
        subject = hmac.new(secret.encode(), source.encode(), hashlib.sha256).hexdigest()
        window = int(self.clock().timestamp()) // window_seconds
        connection.execute("DELETE FROM verification_windows WHERE window < ?", (window - 1,))
        result = connection.execute(
            """INSERT INTO verification_windows VALUES (?, ?, 1)
               ON CONFLICT(subject, window) DO UPDATE SET attempts = attempts + 1
               WHERE attempts < ?""",
            (subject, window, limit),
        )
        return result.rowcount != 0

    def check_ready(self):
        with closing(self.database.connect()) as connection:
            connection.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()

    @contextmanager
    def transaction(self):
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def create(self) -> tuple[SessionState, str]:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        state = SessionState(session_id=uuid4().hex, created_at=now, updated_at=now)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (state.session_id, token_hash(token), state.model_dump_json()),
            )
            self.audit(connection, state, "session_created")
        return state, token

    def load(self, connection, session_id: str, token: str) -> SessionState:
        row = connection.execute(
            "SELECT token_hash, state FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None or not secrets.compare_digest(row["token_hash"], token_hash(token)):
            raise SessionUnavailable()
        state = SessionState.model_validate_json(row["state"])
        if self.clock() >= state.updated_at + self.ttl:
            raise SessionUnavailable()
        return state

    def get(self, session_id: str, token: str) -> SessionState:
        with closing(self.database.connect()) as connection:
            return self.load(connection, session_id, token)

    def save(self, connection, state: SessionState) -> SessionState:
        state = state.model_copy(update={"version": state.version + 1, "updated_at": self.clock()})
        connection.execute(
            "UPDATE sessions SET state = ? WHERE session_id = ?",
            (state.model_dump_json(), state.session_id),
        )
        return state

    def audit(self, connection, state, event_type, *, action=None, decision=None, reason=None):
        event = AuditEvent(
            session_id=state.session_id, timestamp=self.clock(), event_type=event_type,
            phase=state.phase, action=action, decision=decision, reason=reason,
        )
        connection.execute(
            "INSERT INTO audit_events(session_id, event) VALUES (?, ?)",
            (state.session_id, event.model_dump_json()),
        )
        return event.event_id

    def audit_events(self, session_id: str) -> list[AuditEvent]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT event FROM audit_events WHERE session_id = ? ORDER BY sequence", (session_id,)
            ).fetchall()
        return [AuditEvent.model_validate_json(row["event"]) for row in rows]

    def chat_turn(self, connection, session_id, message_id):
        return connection.execute(
            "SELECT digest, result FROM chat_turns WHERE session_id = ? AND message_id = ?",
            (session_id, message_id),
        ).fetchone()

    def save_chat_turn(self, connection, session_id, message_id, digest, safe_input, result):
        connection.execute("INSERT INTO chat_turns VALUES (?, ?, ?, ?, ?)",
                           (session_id, message_id, digest, safe_input, result))

    def history(self, connection, session_id, limit):
        rows = connection.execute(
            "SELECT safe_input FROM chat_turns WHERE session_id = ? ORDER BY rowid DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [row["safe_input"] for row in reversed(rows)]

    def transcript(self, connection, state):
        rows = connection.execute(
            "SELECT message_id, result FROM chat_turns WHERE session_id = ? ORDER BY rowid DESC LIMIT 30",
            (state.session_id,),
        ).fetchall()
        replies = []
        for row in reversed(rows):
            reply = json.loads(row["result"])
            if reply["phase"] == Phase.VERIFY_ID.value or (
                state.identity_verified and state.status in {SessionStatus.ACTIVE, SessionStatus.COMPLETED}
            ):
                replies.append({"message_id": row["message_id"], "response": reply["response"]})
        return replies
