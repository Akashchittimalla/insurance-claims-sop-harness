from enum import Enum
import re

from pydantic import Field

from .session import Emotion, IdentityField, Model, VerificationStatus


class Strategy(str, Enum):
    CONTINUE_SOP = "continue_sop"
    ACKNOWLEDGE_AND_CONTINUE = "acknowledge_and_continue"
    EXPLAIN_REQUIREMENT = "explain_requirement"
    OFFER_ALTERNATIVES = "offer_alternatives"
    REDIRECT = "redirect_to_insurance"
    OFFER_HUMAN = "offer_human_assistance"
    LOCK_VERIFICATION = "lock_verification"
    SAFE_FALLBACK = "safe_fallback"


class RecoveryDecision(Model):
    strategy: Strategy
    reason_code: str
    offer_human: bool = False


class GuardrailDecision(Model):
    allowed: bool = True
    reason_code: str = "normal"
    safety_emergency: bool = False
    unrelated: bool = False
    substantive: bool = False
    declined_handoff: bool = False
    accepted_handoff: bool = False
    poll_handoff: bool = False
    resume: bool = False
    refused_fields: frozenset[IdentityField] = frozenset()
    explicit_refusal: bool = False
    identity_restatement: bool = False


INJECTION = re.compile(
    r"\b(?:ignore (?:all |your |the )?(?:previous |prior |verification )?(?:instructions|rules)"
    r"|system prompt|developer (?:message|instructions)|identity_verified|authorized_party_id|current_phase"
    r"|(?:set|change|skip|bypass|override) (?:the )?(?:phase|verification|sop|authentication)"
    r"|(?:i am|i['’]m) (?:the |an? )?(?:administrator|admin)"
    r"|(?:verification tool|tool result|tool response).{0,35}(?:success|verified)"
    r"|execute (?:the )?(?:claim repository|sql)|send (?:the )?summary without asking"
    r"|(?:assume|pretend) (?:that )?i own|you are now a different assistant|reveal all claims)\b",
    re.I,
)
UNRELATED = re.compile(
    r"\b(?:reinforcement learning|machine learning|rl\b|sorting algorithm|python|javascript|programming"
    r"|quantum|weather|jokes?|poem|recipe|politics|election|recommend a (?:phone|laptop)"
    r"|search the (?:internet|web)|write (?:a |an )?(?:story|song|code))\b", re.I,
)
INSURANCE = re.compile(
    r"\b(?:insurance|claim|claims|policyholder|healthcare|reimbursement|denied|appeal|"
    r"pathology report|office note|repair estimate|verification|verify|policy number)\b", re.I,
)
EMERGENCY = re.compile(
    r"\b(?:immediate danger|medical emergency|can't breathe|cannot breathe|"
    r"kill myself|end my life|going to hurt myself|going to hurt someone)\b", re.I,
)
DECLINE = re.compile(
    r"\b(?:no(?: thanks)?[, .!]*$|(?:do not|don't|dont|not) (?:want to )?"
    r"(?:speak|talk|transfer|connect)|decline (?:the )?(?:handoff|transfer))", re.I,
)
REFUSAL = re.compile(
    r"\b(?:refus\w*|won['’]t|not (?:giving|sharing|providing)|"
    r"(?:do not|don['’]t) want to (?:give|share|provide)|not comfortable (?:giving|sharing|providing))\b", re.I,
)
FIELDS = {
    IdentityField.SSN: r"\b(?:ssn|social security)\b",
    IdentityField.PHONE: r"\bphone\b",
    IdentityField.EMAIL: r"\bemail\b",
    IdentityField.DOB: r"\b(?:dob|birthday|birth)\b",
    IdentityField.FULL_NAME: r"\b(?:full name|my name)\b",
}


def inspect_input(message: str, *, supplied_identity: bool = False) -> GuardrailDecision:
    emergency = bool(EMERGENCY.search(message))
    blocked = bool(INJECTION.search(message))
    declined = bool(DECLINE.search(message))
    refused = bool(REFUSAL.search(message))
    fields = frozenset(field for field, pattern in FIELDS.items() if refused and re.search(pattern, message, re.I))
    return GuardrailDecision(
        allowed=not blocked and not emergency,
        reason_code="immediate_safety" if emergency else "prompt_injection" if blocked else "normal",
        safety_emergency=emergency,
        unrelated=bool(UNRELATED.search(message)),
        substantive=supplied_identity or bool(INSURANCE.search(message)),
        declined_handoff=declined,
        accepted_handoff=not declined and bool(re.fullmatch(r"\s*(?:yes|yes please|please do|connect me)[.! ]*", message, re.I)),
        poll_handoff=bool(re.fullmatch(r"\s*(?:handoff status|transfer status|check (?:the )?(?:handoff|transfer))[?.! ]*", message, re.I)),
        resume=bool(re.fullmatch(r"\s*(?:resume|continue (?:my )?(?:claim|chat|verification)|cancel (?:the )?(?:handoff|transfer))[.! ]*", message, re.I)),
        refused_fields=fields,
        explicit_refusal=refused and bool(fields or re.search(
            r"\b(?:anything|any more|any information|any (?:of (?:those|these)|details)|verif\w*)\b", message, re.I,
        )),
        identity_restatement=bool(re.search(
            r"\b(?:my (?:full )?name is|my (?:dob|birthday|date of birth)|my (?:email|phone)|my ssn)\b",
            message, re.I,
        )),
    )


class RecoveryPolicy:
    def __init__(self, settings):
        self.settings = settings

    def decide(self, state, *, out_of_scope=False, refused=False, failed=False) -> RecoveryDecision:
        if state.verification == VerificationStatus.LOCKED:
            return RecoveryDecision(strategy=Strategy.LOCK_VERIFICATION, reason_code="verification_locked")
        reason = (
            "dependency_failure" if failed and state.recovery.dependency_failures >= self.settings.max_dependency_failures
            else "repeated_refusal" if state.refusal_count >= self.settings.max_verification_refusals
            else "scope_limit" if state.out_of_scope_count >= self.settings.max_out_of_scope_attempts
            else "repeated_frustration" if state.recovery.frustration_count >= self.settings.max_recovery_attempts
            else "recovery_limit" if state.recovery.stalled_turns >= self.settings.max_recovery_attempts
            else None
        )
        if reason and reason != state.recovery.declined_reason and not state.recovery.offer_reason:
            return RecoveryDecision(strategy=Strategy.OFFER_HUMAN, reason_code=reason, offer_human=True)
        if failed:
            return RecoveryDecision(strategy=Strategy.SAFE_FALLBACK, reason_code="dependency_failure")
        if out_of_scope:
            return RecoveryDecision(strategy=Strategy.REDIRECT, reason_code="outside_insurance_scope")
        if refused:
            return RecoveryDecision(strategy=Strategy.OFFER_ALTERNATIVES, reason_code="identity_refusal")
        if state.emotion not in {None, Emotion.NEUTRAL}:
            return RecoveryDecision(strategy=Strategy.ACKNOWLEDGE_AND_CONTINUE, reason_code="emotion_detected")
        return RecoveryDecision(strategy=Strategy.CONTINUE_SOP, reason_code="normal")


def empathy(emotion: Emotion, previous: Emotion | None) -> str:
    if emotion in {Emotion.ANGRY, Emotion.FRUSTRATED}:
        return ("I know this is frustrating. Let’s focus on what’s still needed. " if previous == emotion
                else "I understand this can be frustrating. ")
    return {
        Emotion.ANXIOUS: "It’s understandable to be worried about this. ",
        Emotion.CONFUSED: "I can explain how this works. ",
        Emotion.DISTRESSED: "Let’s take this one step at a time. ",
    }.get(emotion, "")


def contains_private_output(text: str) -> bool:
    return bool(re.search(
        r"\b\d{3}-\d{2}-\d{4}\b|[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}"
        r"|\b(?:SSN|social security number)\s*(?:ends in|is|:)\s*\d{4}\b"
        r"|\b(?:dob|date of birth)\s*(?:is|:)\s*\d{4}-\d{2}-\d{2}\b"
        r"|(?<!\d)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)",
        text, re.I,
    ))
