from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import logging
import re
from string import Formatter
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from .fixtures_loader import ClaimRecord, DocumentGuidance
from .session import Discussion, Intent


LOGGER = logging.getLogger(__name__)


ALIASES = {
    "pathology report": "original pathology report",
    "office note": "treating provider office note",
}
FINANCIAL_LABELS = {
    "net_pay": "Recorded payment",
    "expected_reimbursement_amount": "Expected reimbursement",
    "allowed_max_amount": "Allowed maximum",
    "net_fee": "Net fee",
}
PROVIDER_SUBMISSION = re.compile(
    r"\b(?:doctor|provider|clinic|hospital|lab|facility)\b.*"
    r"\b(?:send|submit|fax|upload|resend)\b"
)


class Topic(str, Enum):
    ALTERNATIVES = "missing_required_material_alternatives"
    TIMING = "submission_timing"
    PROCESSING = "processing_time_after_submission"
    METHOD = "submission_method"
    FORMAT = "file_format_requirements"
    RECEIPT = "receipt_confirmation"


class DeadlineStatus(str, Enum):
    UPCOMING = "upcoming"
    DUE_TODAY = "due_today"
    PASSED = "passed"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str
    field: str
    session_id: str
    party_id: str
    case_id: str
    retrieved_at: datetime
    text: str

    @property
    def reference(self) -> str:
        return f"{self.source}:{self.field}"


class AppealInformation(BaseModel):
    deadline: date | None
    status: DeadlineStatus


def appeal_information(deadline: date | None, today: date) -> AppealInformation:
    status = DeadlineStatus.UNKNOWN
    if deadline is not None:
        status = (DeadlineStatus.PASSED if deadline < today else
                  DeadlineStatus.DUE_TODAY if deadline == today else DeadlineStatus.UPCOMING)
    return AppealInformation(deadline=deadline, status=status)


def normalize_document(name: str) -> str:
    name = " ".join(name.casefold().split())
    return ALIASES.get(name, name)


def infer_topics(question: str) -> tuple[Topic, ...]:
    patterns = (
        (Topic.ALTERNATIVES, r"\b(?:cannot|can't|don't have|do not have|could not|unable|anymore|alternatives?|substitute|replacement|nothing else|tried everything|exhausted)\b"),
        (Topic.TIMING, r"\b(?:by when|when (?:do i need to|should i|must i)|how soon (?:do i need|should i)|submission deadline|submit by)\b"),
        (Topic.PROCESSING, r"\b(?:how long|processing time|processing take|review time|review it again|approved tomorrow)\b"),
        (Topic.METHOD, r"\b(?:how (?:do|can|should) i (?:submit|send|upload)|where|portal|upload (?:link|it online)|fax|mail)\b"),
        (Topic.FORMAT, r"\b(?:pdf|scan(?:ned)?|format|image|resolution|file size|clear enough)\b"),
        (Topic.RECEIPT, r"\b(?:received|receipt|got it|get confirmation|confirm receipt|status reflect)\b"),
    )
    topics = tuple(topic for topic, pattern in patterns if re.search(pattern, question))
    if Topic.METHOD not in topics and PROVIDER_SUBMISSION.search(question):
        return (*topics, Topic.METHOD)
    return topics


COMPATIBLE_INTENTS = {
    Intent.DOCUMENT_SUBMISSION: {"document_submission"},
    Intent.DOCUMENT_REQUIREMENTS: {"document_submission", "next_steps"},
    Intent.DOCUMENT_ALTERNATIVES: {"document_submission", "next_steps", "general_claim_question"},
    Intent.CLAIM_DOCUMENTS: {"document_submission"},
    Intent.CLAIM_DENIAL: {"denial_question", "next_steps"},
    Intent.CLAIM_DELAY: {"status_inquiry", "general_claim_question"},
    Intent.CLAIM_STATUS: {"status_inquiry"},
    Intent.GENERAL_CLAIM_QUESTION: {"general_claim_question", "next_steps"},
}


class ClaimProcessing:
    def __init__(self, knowledge, clock, timezone):
        self.knowledge, self.clock, self.timezone = knowledge, clock, timezone

    def get_guidelines(self) -> DocumentGuidance:
        started = perf_counter()
        result = DocumentGuidance.model_validate(self.knowledge.required_document_guideline())
        LOGGER.info("approved knowledge=%s latency_ms=%.3f", "document_guidance", (perf_counter() - started) * 1000)
        return result

    def field_definition(self, field: str) -> str:
        return self.knowledge.claim_schema()["field_descriptions"][field]["description"]

    def deadline(self, claim: ClaimRecord) -> AppealInformation:
        return appeal_information(claim.appeal_deadline, self.clock().astimezone(self.timezone).date())

    @staticmethod
    def document_text(guides, case_type: str, document: str, alternative: bool = False):
        key = normalize_document(document)
        if alternative:
            rows = guides.document_alternative_guidance
            return ("document_alternative_guidance." + (key if key in rows else "default"),
                    rows.get(key, rows.get("default", {})).get("en"))
        row = guides.document_guidance.get(key, {}).get("en")
        if row:
            return f"document_guidance.{key}", row
        row = guides.case_type_guidance.get(case_type, {}).get("en")
        if row:
            return f"case_type_guidance.{case_type}", row
        return "default_guidance", guides.default_guidance.get("en")

    @staticmethod
    def followup(guides, claim, topic, intents):
        compatible = set().union(*(COMPATIBLE_INTENTS.get(i, set()) for i in intents))
        for rule in guides.claim_followup_guidance:
            if rule.topic != topic.value:
                continue
            if rule.requires_documents and not claim.documents_needed:
                break
            if not compatible.intersection(rule.intent_hints):
                break
            # A paraphrase or typed semantic topic can select a rule; exact phrase hints
            # also participate in routing when the same intent is eligible.
            values = {
                "case_id": claim.case_id,
                "documents": ", ".join(claim.documents_needed or ()),
                "average_processing_time_after_submission": guides.claim_followup_settings.get(
                    "average_processing_time_after_submission", {}).get("en"),
            }
            try:
                parsed = list(Formatter().parse(rule.en))
                if not all(field is None or (field in values and values[field] and not spec and not conversion)
                           for _, field, spec, conversion in parsed):
                    break
                return f"claim_followup_guidance.{rule.topic}", rule.en.format_map(values)
            except ValueError:
                break
        return "claim_followup_fallback", (
            guides.claim_followup_fallback.get("en") if claim.documents_needed
            else "This record does not list required documents for that follow-up."
        )

    def answer(self, state, claim, question, intents, topics, amounts):
        if claim.party_id != state.authorized_party_id or claim.case_id != state.resolved_case_id:
            raise PermissionError("Evidence scope mismatch")
        previous = state.discussion if state.discussion.case_id == claim.case_id else Discussion(case_id=claim.case_id)
        evidence = []
        pending = []
        finished = []
        stamp = self.clock()

        def add(source, field, text):
            if source == "guideline" and text and re.search(
                r"\b(?:ignore (?:all |previous |the )?(?:instructions|rules)|"
                r"system prompt|override (?:the )?(?:sop|verification)|identity_verified)\b",
                text, re.I,
            ):
                return
            if text and not any(item.text == text for item in evidence):
                evidence.append(Evidence(source=source, field=field, session_id=state.session_id,
                                         party_id=claim.party_id, case_id=claim.case_id,
                                         retrieved_at=stamp, text=text))

        def fact(field, text):
            add("claim", field, text)

        documents = claim.documents_needed or ()
        topics = tuple(dict.fromkeys(topics))
        finance = Intent.CLAIM_PAYMENT in intents or bool(amounts) or bool(re.search(
            r"\b(?:net fee|net pay|allowed max(?:imum)?|expected reimbursement|balance|deductible|copay|responsibility)\b", question
        ))
        ask_documents = bool(intents.intersection({
            Intent.CLAIM_DOCUMENTS, Intent.DOCUMENT_REQUIREMENTS, Intent.DOCUMENT_ALTERNATIVES,
        }))
        guides = self.get_guidelines()
        topic_by_name = {topic.value: topic for topic in Topic}
        fixture_matches = [
            topic_by_name[rule.topic] for rule in guides.claim_followup_guidance
            if rule.topic in topic_by_name and any(phrase in question for phrase in rule.match_any)
        ]
        topics = tuple(dict.fromkeys((*topics, *fixture_matches)))
        names = sorted(set(documents) | set(guides.document_guidance) | set(ALIASES), key=len, reverse=True)
        selected = next((name for name in names if re.search(rf"\b{re.escape(name)}\b", question)), None)
        if selected:
            selected = next((name for name in documents if normalize_document(name) == normalize_document(selected)), selected)
        if not selected and re.search(r"\b(?:it|that report|original report|that document|that one)\b", question):
            selected = previous.document or (documents[0] if len(documents) == 1 else None)
        if not selected and re.search(r"\[redacted\]\s+(?:report|document|record|form)\b", question):
            selected = "document without a matching guideline"

        if Intent.CLAIM_STATUS in intents or Intent.GENERAL_CLAIM_QUESTION in intents:
            fact("status", f"The recorded claim status is {claim.status}.")
            fact("summary", claim.summary.rstrip(".") + "." if claim.summary else None)
            finished.append("status")
        if Intent.CLAIM_DENIAL in intents:
            fact("status", f"The recorded claim status is {claim.status}.")
            if claim.denial_reason:
                fact("denial_reason", f"The recorded denial reason is that {claim.denial_reason.rstrip('.')}.")
            elif claim.status == "denied":
                fact("denial_reason", "The record does not give a denial reason. A claims representative can help review it.")
            finished.append("denial")
        if ask_documents or Intent.CLAIM_DENIAL in intents:
            fact("documents_needed", "Documents listed as needed: " + ", ".join(documents) + "."
                 if documents else "This claim record does not list any required documents.")
            finished.append("missing_documents")

        alternative = Topic.ALTERNATIVES in topics or Intent.DOCUMENT_ALTERNATIVES in intents
        requirements = ask_documents or bool(re.search(r"\b(?:contain|what about|what should|requirements)\b", question))
        discuss_document = selected and (requirements or alternative or Topic.FORMAT in topics)
        ambiguous = not selected and (alternative or requirements) and (
            (bool(documents) and bool(re.search(r"\b(?:it|contain|original report|that report)\b", question)))
            or (alternative and len(documents) > 1)
        )
        if alternative and re.search(r"\b(?:tried everything|none of|no alternatives|exhausted|nothing else|cannot get any)\b", question):
            key = "human_review_after_document_alternatives_exhausted"
            add("guideline", f"claim_followup_settings.{key}", guides.claim_followup_settings.get(key, {}).get("en"))
            if (not state.recovery.offer_reason
                    and state.recovery.declined_reason != "document_alternatives_exhausted"):
                add("workflow", "human_offer", "Would you like help from a human claims representative?")
            finished.append("manual_review")
        elif ambiguous and len(documents) > 1:
            fact("documents_needed", "Which document do you mean: " + " or ".join(documents) + "?")
            pending.append("document_reference")
        elif discuss_document or alternative:
            field, text = self.document_text(guides, claim.case_type, selected or "", alternative)
            if not field.startswith("document_guidance.") and not alternative:
                add("guideline", field, "No document-specific rule is available. General guidance: " + text if text else None)
            else:
                add("guideline", field, text)
            if alternative:
                add("guideline", "alternatives_limit", "A substitute may be reviewed, and acceptance is subject to review.")
            if selected and normalize_document(selected) == "original pathology report" and not alternative:
                add("claim", "documents_needed.original", "The record lists a pathology report and does not specify an original.")
            finished.append("alternatives" if alternative else "requirements")

        for topic in topics:
            if topic == Topic.ALTERNATIVES and (ambiguous or alternative):
                continue
            if topic == Topic.FORMAT and discuss_document:
                if re.search(r"\b(?:file size|resolution|compression)\b", question):
                    add("guideline", "format_limit", "The available guidance does not give that technical upload specification.")
                continue
            if topic == Topic.METHOD and selected and PROVIDER_SUBMISSION.search(question):
                key = normalize_document(selected)
                direct = guides.document_alternative_guidance.get(key, {}).get("en")
                if direct and re.search(r"\b(?:directly|resent)\b", direct):
                    add("guideline", f"document_alternative_guidance.{key}", direct)
                    finished.append(topic.value)
                    continue
            field, text = self.followup(guides, claim, topic, intents)
            if field == "claim_followup_fallback" and topic == Topic.METHOD:
                field, text = "default_guidance", guides.default_guidance.get("en")
            add("guideline", field, text)
            if topic == Topic.TIMING and field != "claim_followup_fallback":
                add("guideline", "timing_limit", "This is a document submission recommendation, separate from any recorded appeal deadline.")
            if topic == Topic.PROCESSING:
                add("guideline", "estimate_limit", "This is an estimate. Approval and a completion date cannot be guaranteed.")
            if topic == Topic.RECEIPT:
                add("claim", "receipt_unavailable", "The record does not confirm whether the insurer received your documents.")
            finished.append(topic.value)

        financial_field = previous.financial_field
        if finance:
            explicitly_named = [field for pattern, field in (
                (r"\b(?:net pay|actually pay|did .* pay|payment)\b", "net_pay"),
                (r"\b(?:expected|reimbursement)\b", "expected_reimbursement_amount"),
                (r"\ballowed max(?:imum)?\b", "allowed_max_amount"),
                (r"\bnet fee\b", "net_fee"),
            ) if re.search(pattern, question)]
            matches = [field for field in FINANCIAL_LABELS if getattr(claim, field) in amounts]
            fields = list(dict.fromkeys([*explicitly_named, *matches])) or (
                [financial_field] if financial_field and re.search(r"\b(?:it|that field|that amount)\b", question)
                else ["net_pay"]
            )
            if amounts and not matches:
                fact("financial_unknown", "I couldn’t match that amount to a recorded financial field. Which field are you looking at?")
                pending.append("financial_field")
            else:
                if any(field != "net_pay" for field in fields):
                    fields.append("net_pay")
                for field in dict.fromkeys(fields):
                    value = getattr(claim, field)
                    fact(field, f"{FINANCIAL_LABELS[field]}: USD {value:.2f}." if value is not None
                         else f"{FINANCIAL_LABELS[field]} is unavailable in this record.")
                    if field != "net_pay":
                        add("financial_schema", field, self.field_definition(field))
                        add("financial_schema", "distinction", "Expected and allowed amounts do not establish an actual or guaranteed payment.")
                financial_field = fields[0]
            if re.search(r"\b(?:balance|deductible|copay|responsibility|owe)\b", question):
                fact("responsibility_unavailable", "The recorded fields do not establish what you owe or any deductible or copayment.")
            finished.append("financial")

        if intents.intersection({Intent.CLAIM_APPEAL, Intent.APPEAL_GUIDANCE}):
            appeal = self.deadline(claim)
            if appeal.deadline is None:
                fact("appeal_deadline", "No appeal deadline is recorded.")
            else:
                descriptions = {DeadlineStatus.PASSED: "has passed", DeadlineStatus.DUE_TODAY: "is today",
                                DeadlineStatus.UPCOMING: "is upcoming"}
                fact("appeal_deadline", f"The recorded appeal deadline is {appeal.deadline.isoformat()}. It {descriptions[appeal.status]}.")
            add("appeal_clock", "eligibility", "The record does not confirm appeal eligibility, an extension, or exceptions. A claims representative can help clarify your options.")
            finished.append("appeal")
        if intents.intersection({Intent.COVERAGE_INQUIRY, Intent.CLAIM_SUBMISSION_GUIDANCE}):
            add("workflow", "unsupported_operation", "This claim record does not establish coverage or eligibility. I can help you contact a claims representative.")
        if not evidence:
            add("workflow", "clarification", "Could you tell me which claim detail or document you’d like help with?")
            pending.append("question")
        outstanding = set(previous.pending) - set(finished)
        if selected or "manual_review" in finished:
            outstanding.discard("document_reference")
        if finance and not pending:
            outstanding.discard("financial_field")
        outstanding.discard("question")
        discussion = previous.model_copy(update={
            "document": selected or previous.document,
            "financial_field": financial_field,
            "completed_topics": tuple(dict.fromkeys((*previous.completed_topics, *finished))),
            "pending": tuple(sorted(outstanding | set(pending))),
            "evidence_refs": tuple(item.reference for item in evidence),
            "guidance_presented": tuple(dict.fromkeys((*previous.guidance_presented, *(
                item.field for item in evidence if item.source == "guideline"
            )))),
            "manual_review_recommended": previous.manual_review_recommended or "manual_review" in finished,
        })
        return evidence, discussion, tuple(finished)
