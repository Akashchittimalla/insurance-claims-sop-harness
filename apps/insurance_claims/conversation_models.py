import json
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .claim_processing import Topic
from .protected_input import MONTHS
from .session import ClaimHints, Emotion, Intent, Model


class Scope(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"


class ConsentCandidate(str, Enum):
    NONE = "none"
    ACCEPT = "accept"
    DECLINE = "decline"
    UNCLEAR = "unclear"


class ProposedAction(Model):
    action_name: Literal[
        "ask_clarification", "verify_identity", "search_customer_claims",
        "get_claim_details", "get_denial_reason", "get_payment_details",
        "get_required_documents", "request_human_transfer", "generate_response",
        "get_claim_status", "get_financial_field_definition", "get_document_guidance",
        "get_document_alternatives", "get_claim_followup_guidance", "get_appeal_information",
    ]
    # Case references and other tool arguments are bound server-side.


class IntentClassification(Model):
    primary_intent: Intent | None = None
    secondary_intents: Annotated[tuple[Intent, ...], Field(max_length=6)] = ()


class ConversationAnalysis(IntentClassification):
    scope: Scope = Scope.UNCERTAIN
    emotion: Emotion = Emotion.NEUTRAL
    emotion_intensity: Annotated[int, Field(ge=0, le=5, strict=True)] = 0
    refusal_detected: bool = False
    human_requested: bool = False
    claim_hints: ClaimHints = ClaimHints()
    clarification_required: bool = False
    suggested_clarification: Annotated[str, StringConstraints(max_length=240)] | None = None
    proposed_action: ProposedAction | None = None
    email_consent_candidate: ConsentCandidate = ConsentCandidate.NONE
    followup_topics: tuple[Topic, ...] = Field(default=(), max_length=6)
    completion_candidate: bool = False


class EvidenceReference(Model):
    source_type: Literal["claim"]
    source_id: Annotated[str, StringConstraints(pattern=r"^CL-[0-9]{1,12}$")]
    fields: tuple[Literal[
        "status", "denial_reason", "documents_needed", "appeal_deadline", "net_pay",
        "expected_reimbursement_amount",
    ], ...] = Field(max_length=6)


class GroundedResponse(Model):
    response_text: Annotated[str, StringConstraints(max_length=600)] = ""
    evidence_references: Annotated[tuple[EvidenceReference, ...], Field(max_length=1)] = ()
    clarification_required: bool = False
    suggested_followup: Annotated[str, StringConstraints(max_length=240)] | None = None
    topics_answered: tuple[str, ...] = Field(default=(), max_length=24)
    unanswered_topics: tuple[str, ...] = Field(default=(), max_length=24)
    evidence_sources: tuple[str, ...] = Field(default=(), max_length=40)


def mock_analysis(messages, schema):
    data = json.loads(messages[-1]["content"])
    if schema is GroundedResponse:
        return {"response_text": data["approved_openers"][0],
                "evidence_references": data["evidence_references"],
                "topics_answered": data.get("topics_answered", []),
                "unanswered_topics": data.get("unanswered_topics", []),
                "evidence_sources": data.get("evidence_sources", [])}
    message = data["message"]
    positive = re.split(r"(?:,?\s+not\s+the|\s+instead of|\s+rather than)", message, maxsplit=1)[0]
    hints = {}
    for names, kind in ((r"healthcare|health|medical", "healthcare"), (r"dental", "dental"),
                        (r"auto|car|accident", "auto")):
        if re.search(rf"\b(?:{names})\b", positive):
            hints["case_type"] = kind
            break
    for terms, status in ((r"denied|reject(?:ed)?|denial", "denied"), (r"settled|closed", "closed"),
                          (r"open", "open")):
        if re.search(rf"\b(?:{terms})\b", positive):
            hints["status"] = status
            break
    for index, month in enumerate(MONTHS, 1):
        if re.search(rf"\b{month}\b", positive):
            hints["month"] = index
            break
    intents = []
    for expression, intent in (
        (r"\b(?:reject(?:ed)?|denied|denial)\b", "CLAIM_DENIAL"),
        (r"\b(?:pay|paid|payment|reimburse\w*|payout)\b", "CLAIM_PAYMENT"),
        (r"\b(?:appeal|challenge)\b", "APPEAL_GUIDANCE"),
        (r"\b(?:upload|submit|submission)\b", "DOCUMENT_SUBMISSION"),
        (r"\b(?:cannot|can't|unable|anymore)\b.*\b(?:document|report|note)\b", "DOCUMENT_ALTERNATIVES"),
        (r"\b(?:document|missing|requirements)\b", "DOCUMENT_REQUIREMENTS"),
        (r"\b(?:delay|processing|waiting|how long)\b", "CLAIM_DELAY"),
        (r"\b(?:coverage|covered)\b", "COVERAGE_INQUIRY"),
    ):
        if re.search(expression, positive):
            intents.append(intent)
    if not intents and re.search(r"\b(?:claim|case|happened)\b", positive) and not re.search(
        r"\b(?:meant|actually|instead)\b", positive
    ):
        intents.append("CLAIM_STATUS")
    unrelated = re.search(r"\b(?:reinforcement learning|weather|quantum|joke|poem|recipe)\b", message)
    relevant = bool(intents or hints or data.get("identity_supplied"))
    emotion = "neutral"
    for terms, label in ((r"ridiculous|frustrated|already told", "frustrated"),
                         (r"angry", "angry"), (r"confused", "confused"),
                         (r"anxious|worried", "anxious"), (r"distressed", "distressed")):
        if re.search(terms, message):
            emotion = label
            break
    return {
        "scope": ("MIXED" if relevant else "OUT_OF_SCOPE") if unrelated else (
            "UNCERTAIN" if "[redacted]" in message and not relevant else "IN_SCOPE"
        ),
        "primary_intent": intents[0] if intents else None,
        "secondary_intents": intents[1:],
        "emotion": emotion,
        "claim_hints": hints,
    }
