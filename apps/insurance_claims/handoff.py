from datetime import datetime
from enum import Enum
from uuid import uuid4

from .session import Intent, Model, SessionState, VerificationStatus
from .sop import Phase


class HandoffStatus(str, Enum):
    REQUESTED = "requested"
    QUEUED = "queued"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HandoffRecord(Model):
    handoff_id: str
    session_id: str
    phase: Phase
    verification: VerificationStatus
    authorized: bool
    representative_status: str
    intent: Intent | None
    authorized_case: str | None
    reason: str
    recovery_steps: tuple[str, ...]
    pending_questions: tuple[str, ...]
    summary: str
    status: HandoffStatus
    timestamp: datetime


class MockHandoff:
    def __init__(self, sessions):
        self.sessions = sessions

    def request(self, connection, state: SessionState, reason: str) -> HandoffRecord:
        if state.handoff_id:
            return self.get(connection, state)
        record = HandoffRecord(
            handoff_id=uuid4().hex, session_id=state.session_id, phase=state.phase,
            verification=state.verification, authorized=state.identity_verified,
            representative_status=state.representative_status.value, intent=state.memory.intent,
            authorized_case=state.resolved_case_id if state.identity_verified and state.claim_ownership_validated else None,
            reason=reason, recovery_steps=state.recovery.steps,
            pending_questions=state.discussion.pending,
            summary="Identity verified." if state.identity_verified else "Identity review required.",
            status=HandoffStatus.REQUESTED, timestamp=self.sessions.clock(),
        )
        connection.execute("INSERT INTO handoff_requests VALUES (?, ?, ?)",
                           (record.handoff_id, state.session_id, record.model_dump_json()))
        return record

    @staticmethod
    def get(connection, state):
        row = connection.execute(
            "SELECT record FROM handoff_requests WHERE handoff_id = ? AND session_id = ?",
            (state.handoff_id, state.session_id),
        ).fetchone()
        if row is None:
            raise LookupError("Handoff unavailable")
        return HandoffRecord.model_validate_json(row[0])

    def update(self, connection, state, *, cancel=False):
        record = self.get(connection, state)
        if record.status not in {HandoffStatus.REQUESTED, HandoffStatus.QUEUED}:
            return record
        status = HandoffStatus.CANCELLED if cancel else HandoffStatus.QUEUED
        record = record.model_copy(update={"status": status})
        connection.execute(
            "UPDATE handoff_requests SET record = ? WHERE handoff_id = ? AND session_id = ?",
            (record.model_dump_json(), record.handoff_id, state.session_id),
        )
        return record
