import hashlib
import json
from typing import Literal

from .database import SQLiteCustomerRepository
from .policy import workflow_state
from .session import EmailStatus, Model, SessionStatus
from .sop import Phase


class SummaryChoice(Model):
    choice: Literal["send", "skip"]
    revision: str


def claim_projection(workflow, state):
    if (state.status != SessionStatus.ACTIVE or not state.identity_verified
            or not state.claim_ownership_validated or not state.resolved_case_id):
        return None
    claim = workflow.claims.get_claim(workflow_state(state), state.resolved_case_id)
    return {"case_id": claim.case_id, "type": claim.case_type,
            "status": claim.status, "created_at": claim.created_at.isoformat()}


def followup(workflow, connection, state):
    if state.phase != Phase.POST_PROCESS or not state.discussion_complete:
        return None
    stored = connection.execute(
        "SELECT preview, disposition FROM summary_outcomes WHERE session_id = ?",
        (state.session_id,),
    ).fetchone()
    if stored:
        return {**json.loads(stored["preview"]), "disposition": stored["disposition"], "actions": []}
    if (state.status != SessionStatus.ACTIVE or not state.identity_verified
            or state.discussion.pending or state.discussion.pending_intents or state.discussion.pending_topics):
        return None
    claim = claim_projection(workflow, state)
    topic_labels = {"status": "Claim status", "denial": "Recorded denial", "missing_documents": "Missing documents",
                    "requirements": "Document guidance", "alternatives": "Document alternatives",
                    "financial": "Payment information", "appeal": "Appeal information", "manual_review": "Human review"}
    topics = [topic_labels.get(topic, topic.replace("_", " ").capitalize())
              for topic in state.discussion.completed_topics]
    documents = []
    if claim and "missing_documents" in state.discussion.completed_topics:
        record = workflow.claims.get_claim(workflow_state(state), claim["case_id"])
        documents = record.details.get("documents_needed") or []
    recipient = SQLiteCustomerRepository(workflow.sessions.database).registered_email(state.authorized_party_id)
    masked = recipient[:1] + "***@" + recipient.partition("@")[2] if recipient and "@" in recipient else None
    preview = {"claim": claim, "topics": topics, "documents": documents, "recipient": masked}
    preview["revision"] = hashlib.sha256(json.dumps([state.version, preview], sort_keys=True).encode()).hexdigest()
    actions = ["skip"]
    if masked and workflow.settings.email_mode == "mock" and workflow.settings.demo_mode:
        actions.insert(0, "send")
    return {**preview, "disposition": "pending", "actions": actions}


def choose_summary(workflow, connection, state, choice: SummaryChoice):
    preview = followup(workflow, connection, state)
    if preview is None or preview["revision"] != choice.revision:
        raise ValueError("Summary changed")
    disposition = "simulated" if choice.choice == "send" else "declined"
    if preview["disposition"] == disposition:
        return state
    if choice.choice not in preview["actions"]:
        raise ValueError("Summary choice unavailable")
    connection.execute(
        "INSERT INTO summary_outcomes(session_id, preview, disposition) VALUES (?, ?, ?)",
        (state.session_id, json.dumps(preview), disposition),
    )
    state = workflow.sessions.save(connection, state.model_copy(update={
        "status": SessionStatus.COMPLETED,
        "email_status": EmailStatus.SENT if choice.choice == "send" else EmailStatus.DECLINED,
        "email_consent_granted": choice.choice == "send",
    }))
    workflow.sessions.audit(connection, state, "summary_consent", decision=choice.choice)
    if choice.choice == "send":
        workflow.sessions.audit(connection, state, "email_delivery_simulated", decision="allowed")
    return state
