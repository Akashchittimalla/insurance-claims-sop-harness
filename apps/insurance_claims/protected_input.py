from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re

from .identity import IdentitySubmission


MONTHS = (
    "january february march april may june july august september october november december"
).split()
MONTH_PATTERN = "|".join(months for months in MONTHS + [item[:3] for item in MONTHS])
DATE_PATTERN = rf"(?:[0-9]{{4}}-[0-9]{{1,2}}-[0-9]{{1,2}}|(?:{MONTH_PATTERN})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{1,2}}/\d{{1,2}}/\d{{4}})"
PATTERNS = {
    "date_of_birth": re.compile(rf"\b(?:dob|date of birth|birthday|birth date|born)\s*(?:is|was|on|:|=)?\s*({DATE_PATTERN})", re.I),
    "ssn_last4": re.compile(r"\b(?:ssn|social security(?: number)?)\s*(?:last (?:four|4)(?: digits)?|ends in|ending in)\s*(?:is|are|:)?\s*([0-9]{4})(?![0-9-])\b", re.I),
    "phone": re.compile(r"(?<![\w-])((?:\+?1[ .-]?)?(?:\([0-9]{3}\)|[0-9]{3})[ .-]?[0-9]{3}[ .-]?[0-9]{4})(?![\w-])"),
    "email": re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.I),
    "policy_id": re.compile(r"\b(POL-[0-9]{1,12})\b", re.I),
    "case_id": re.compile(r"\b(CL-[0-9]{1,12})\b", re.I),
    "national_id": re.compile(r"\bnational id\s*(?:last (?:four|4)|ends in)\s*(?:is|:)?\s*([0-9]{4})\b", re.I),
}
NAME = re.compile(
    r"\b(?i:my (?:full )?name is|this is|i am|i['’]m)\s+"
    r"((?:[A-Z][^\W\d_]*(?:[-'][^\W\d_]+)?\s+){1,3}[A-Z][^\W\d_]*(?:[-'][^\W\d_]+)?)"
    r"(?=\s*(?:[,.!?;]|$|\band\b|\bpolicy\b))"
)
EXPLICIT_NAME = re.compile(
    r"\bmy (?:full )?name is\s+"
    r"((?:[^\W\d_]+(?:[-'][^\W\d_]+)?\s+){1,3}?[^\W\d_]+(?:[-'][^\W\d_]+)?)"
    r"(?=\s*(?:[,.!?;]|$|\band\b|\bpolicy\b))",
    re.I,
)
REPRESENTATIVE = re.compile(r"\b(?:calling (?:on behalf of|for (?:my|someone))|representative for|i(?:['’]m| am) (?:the |an? )?(?:representative|son|daughter|spouse)|my (?:mother|father|wife|husband)'s claim)\b", re.I)
REFUSAL = re.compile(r"\b(?:refuse|won['’]t|not (?:giving|sharing|providing)|don['’]t want to (?:share|give|provide))\b.{0,45}\b(?:ssn|social security|dob|birthday|phone|email|verif\w*)", re.I)
HUMAN = re.compile(r"\b(?:(?:talk|speak|connect|transfer)\b.{0,35}|(?:want|need)\s+(?:a |an )?)\b(?:someone|person|human|representative|agent)\b", re.I)
CORRECTION = re.compile(r"\b(?:actually|correction|wrong|correct|meant|instead|not)\b", re.I)

# Only these natural-language tokens reach the model. Unknown words and numbers are placeholders.
VOCABULARY = frozenset(("""
    i im i'm am my me you your yours they them it its the a an this that those to is are was were be
    been have has had do did does can could would should will want need may might about with for from
    in on at of and or but also no not yes okay ok sure thanks thank hello hi hey please how why when
    where what who which there any something happened already told giving give gave provide provided
    providing refuse refusing share sharing information ridiculous frustrated angry upset anxious
    confused worried distressed understand verify verification protect identity full name dob date
    birth birthday phone email ssn social security number four caller policyholder policy holder
    representative behalf son daughter spouse human someone person transfer agent talk speak
    insurance insured claim claims case cases medical healthcare health dental auto car accident
    rejected reject denied denial declined settled closed open pending paid pay payment payments
    payout reimburse reimbursement covered coverage policy policies status delay delayed approval
    approved submitted submit submission upload send documents document records record report
    pathology office note alternative alternatives cannot can't cant unable obtain get anymore
    doctor provider clinic hospital lab facility directly resend
    required requirements missing appeal challenge decision processing wait waiting longer long
    received receipt format deadline next steps help assist refund earlier later this last year
    month one two correct correction actually meant instead wrong different original treating
    provider reinforcement learning explain quantum physics weather jokes joke poem recipe
    birthday dates welcome assistance yesterday today recent recently regarding asking calling
    issue additional file files form forms now look check look-up came rejected frustration
    exactly contain original clinic us online scanned pdf scan image resolution size format fax mail portal
    receipt received confirmation got within everything that's answers that's all done
    don't dont cannot could couldn't gave anymore signed signature specimen copies copy
    else own amount amounts actual actually net fee maximum max allowed expected deductible
    copay owe balance responsibility amount tried none exhausted attachments attached day days
    technical requirement next under reopened extension eligibility late deadline eligible
    accident scene photos photo supplemental repair estimate diagnosis treating provider
    until approved tomorrow still processed how soon by scanned file requirements
    other more photos submitted arrived track what's
    continue compression guarantees approved automatically next
""").split()) | frozenset(MONTHS)


@dataclass(frozen=True)
class ProtectedInput:
    identity: IdentitySubmission | None
    sanitized: str
    case_id: str | None
    policy_id: str | None
    explicit_year: int | None
    refusal: bool
    human_requested: bool
    correction: bool
    identity_uncertain: bool = False
    amounts: tuple[Decimal, ...] = ()
    completion_requested: bool = False
    claim_date: date | None = None


def parse_date(text: str, previous: date | None) -> date | None:
    text = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", text)
    text = text.replace(",", "")
    if text[-1:].isdigit() and " " in text and not re.search(r"\b\d{4}$", text) and previous:
        text += f" {previous.year}"
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def protect(message: str, today: date, previous_dob: date | None = None) -> ProtectedInput:
    values = {}
    spans = []
    case_id = None
    uncertain = False
    for field, pattern in PATTERNS.items():
        hits = list(pattern.finditer(message))
        if not hits:
            continue
        spans.extend((hit.start(1), hit.end(1), field) for hit in hits)
        value = hits[0].group(1)
        if field == "date_of_birth":
            for hit in hits:
                alternative = re.match(rf"\s*,?\s*not\s+({DATE_PATTERN})", message[hit.end():], re.I)
                if alternative:
                    spans.append((hit.end() + alternative.start(1),
                                  hit.end() + alternative.end(1), field))
            value = parse_date(value, previous_dob)
            uncertain = value is None
        elif field == "case_id":
            case_id = value.upper()
            continue
        elif field == "national_id":
            continue
        elif field == "policy_id":
            value = value.upper()
        if value is not None:
            values[field] = value
    names = list(NAME.finditer(message)) or list(EXPLICIT_NAME.finditer(message))
    if names:
        values["full_name"] = names[0].group(1)
        spans.extend((hit.start(1), hit.end(1), "full_name") for hit in names)
    representative = bool(REPRESENTATIVE.search(message))
    if representative:
        values["caller_role"] = "representative"
        if "full_name" in values:
            values["representative_name"] = values.pop("full_name")
    elif re.search(r"\bi(?:['’]m| am) (?:the |a )?policyholder\b", message, re.I) or "full_name" in values:
        values["caller_role"] = "policyholder"
    masked = message
    for start, end, field in sorted(spans, reverse=True):
        masked = masked[:start] + " " * (end - start) + masked[end:]
    # Preserve explicit claim years locally, but never pass raw numbers to the model.
    year = None
    match = re.search(rf"\b(?:{MONTH_PATTERN})\s+(20[0-9]{{2}})\b", masked, re.I)
    if match:
        year = int(match.group(1))
    elif re.search(r"\bthis year\b", masked, re.I):
        year = today.year
    elif re.search(r"\blast year\b", masked, re.I):
        year = today.year - 1
    tokens = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+|[?.!,]", masked.lower())
    safe = []
    for token in tokens:
        token = token.replace("’", "'")
        if token in VOCABULARY or token in "?.!,":
            safe.append(token)
        elif not safe or safe[-1] != "[redacted]":
            safe.append("[redacted]")
    human_request = HUMAN.search(message)
    human_requested = bool(human_request and not re.search(
        r"\b(?:do not|don['’]t|not|never)\s+$",
        message[max(0, human_request.start() - 16):human_request.start()], re.I,
    ))
    amounts = tuple(Decimal(match.replace(",", "")) for match in re.findall(
        r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]{1,12}(?:\.[0-9]{1,2})?)",
        masked,
    ))
    completion = bool(re.fullmatch(
        r"(?:no[, ]+)?(?:that['’]s (?:all(?: i needed)?|everything)|"
        r"i have no (?:other |more )?questions|(?:thank you[, ]+)?that answers everything|"
        r"i understand what to do now)[.! ]*(?:thank you[.! ]*)?",
        message.strip(), re.I,
    ))
    claim_date_match = re.search(rf"\b(?:from|created on|filed on|dated)\s+({DATE_PATTERN})", masked, re.I)
    return ProtectedInput(
        IdentitySubmission(**values) if values else None,
        " ".join(safe), case_id, values.get("policy_id"), year,
        bool(REFUSAL.search(message)), human_requested,
        bool(CORRECTION.search(message)), uncertain, amounts, completion,
        parse_date(claim_date_match.group(1), None) if claim_date_match else None,
    )
