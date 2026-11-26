from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import uuid4

from .fixtures_loader import ConsentStatus
from .session import Model, SQLiteSessions, SessionState
from .database import SQLiteKnowledgeRepository


class ConsentPurpose(str, Enum):
    SIMULATION = "simulation"
    REPRESENTATIVE_ACCESS = "representative_access"
    SUMMARY_EMAIL = "summary_email"


class ConsentRequest(Model):
    request_id: str
    session_id: str
    party_id: str
    purpose: ConsentPurpose
    scenario: str
    expires_at: datetime
    authorization_context: str
    poll_count: int = 0
    position: int = 0
    status: ConsentStatus = ConsentStatus.PENDING


class ConsentRepository(Protocol):
    def get(self, connection, session_id: str, request_id: str) -> ConsentRequest: ...
    def save(self, connection, request: ConsentRequest) -> None: ...


class SQLiteConsentRepository:
    def get(self, connection, session_id: str, request_id: str) -> ConsentRequest:
        row = connection.execute(
            "SELECT state FROM consent_requests WHERE request_id = ? AND session_id = ?",
            (request_id, session_id),
        ).fetchone()
        if row is None:
            raise LookupError("Consent request unavailable")
        return ConsentRequest.model_validate_json(row["state"])

    def save(self, connection, request: ConsentRequest) -> None:
        connection.execute(
            """INSERT INTO consent_requests VALUES (?, ?, ?)
               ON CONFLICT(request_id) DO UPDATE SET state = excluded.state
               WHERE consent_requests.session_id = excluded.session_id""",
            (request.request_id, request.session_id, request.model_dump_json()),
        )


class ConsentSimulator:
    def __init__(self, sessions: SQLiteSessions, knowledge: SQLiteKnowledgeRepository,
                 repository: ConsentRepository, max_polls: int):
        self.sessions = sessions
        self.knowledge = knowledge
        self.repository = repository
        self.max_polls = max_polls

    def create(self, connection, session: SessionState, scenario: str, purpose: ConsentPurpose,
               authorization_context: str) -> ConsentRequest:
        if purpose != ConsentPurpose.SIMULATION or not session.identity_verified:
            raise PermissionError("The fixture supports verified simulation sessions only")
        self.knowledge.consent_status_sequence(scenario)
        request = ConsentRequest(
            request_id=uuid4().hex, session_id=session.session_id, party_id=session.authorized_party_id,
            expires_at=self.sessions.clock() + self.sessions.ttl, purpose=purpose, scenario=scenario,
            authorization_context=authorization_context,
        )
        self.repository.save(connection, request)
        self.sessions.audit(connection, session, "consent_created", reason=purpose.value)
        return request

    def update(self, connection, session: SessionState, request_id: str, purpose: ConsentPurpose,
               *, cancel: bool = False) -> ConsentRequest:
        request = self.repository.get(connection, session.session_id, request_id)
        if request.purpose != purpose or request.party_id != session.authorized_party_id:
            raise LookupError("Consent request unavailable")
        if request.status not in {ConsentStatus.PENDING, ConsentStatus.APPROVED}:
            return request
        if self.sessions.clock() >= request.expires_at:
            updates = {"status": ConsentStatus.EXPIRED}
        elif cancel:
            updates = {"status": ConsentStatus.CANCELLED}
        elif request.status == ConsentStatus.APPROVED:
            return request
        else:
            sequence = self.knowledge.consent_status_sequence(request.scenario)
            polls = request.poll_count + 1
            position = min(request.position + 1, len(sequence))
            status = ConsentStatus(sequence[position - 1])
            if status == ConsentStatus.PENDING and polls >= self.max_polls:
                status = ConsentStatus.TIMED_OUT
            updates = {"status": status, "position": position, "poll_count": polls}
        request = request.model_copy(update=updates)
        self.repository.save(connection, request)
        event = "consent_timeout" if request.status == ConsentStatus.TIMED_OUT else "consent_updated"
        self.sessions.audit(connection, session, event, reason=request.status.value)
        return request
