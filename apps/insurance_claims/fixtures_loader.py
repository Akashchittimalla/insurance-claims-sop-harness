from datetime import date
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, ValidationError
from pydantic.functional_validators import BeforeValidator


FIXTURES = Path(__file__).with_name("fixtures")


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("expected an ISO YYYY-MM-DD date")
    return date.fromisoformat(value)


def amount(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+\.[0-9]{2}", value):
        raise ValueError("expected a USD decimal string with two fractional digits")
    return Decimal(value)


Date = Annotated[date, BeforeValidator(iso_date)]
Money = Annotated[Decimal, BeforeValidator(amount)]
LastFour = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]{4}$")]


class Policyholder(FixtureModel):
    party_id: StrictStr
    name: StrictStr
    policy_number: StrictStr
    dob: Date
    id_type: Literal["ssn_last4", "national_id_last4"]
    id_last4: LastFour
    phone: StrictStr
    email: StrictStr
    name_aliases: tuple[StrictStr, ...] = ()
    phone_aliases: tuple[StrictStr, ...] = ()
    email_aliases: tuple[StrictStr, ...] = ()


class ClaimRecord(FixtureModel):
    case_id: StrictStr
    party_id: StrictStr
    case_type: StrictStr
    created_at: Date
    status: StrictStr
    summary: StrictStr
    denial_reason: StrictStr | None = None
    documents_needed: tuple[StrictStr, ...] | None = None
    appeal_deadline: Date | None = None
    expected_reimbursement_amount: Money | None = None
    allowed_max_amount: Money | None = None
    net_pay: Money | None = None
    net_fee: Money | None = None


class Representative(FixtureModel):
    rep_name: StrictStr
    relationship: StrictStr
    buyer_name: StrictStr
    buyer_party_id: StrictStr


class ConsentStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    TIMED_OUT = "timed_out"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConsentScenario(FixtureModel):
    status_sequence: Annotated[tuple[Literal[ConsentStatus.PENDING, ConsentStatus.APPROVED], ...], Field(min_length=1)]


class FinancialField(FixtureModel):
    type: Literal["string"]
    example: Money
    description: StrictStr


class ClaimSchema(FixtureModel):
    notes: tuple[StrictStr, ...]
    field_descriptions: dict[str, FinancialField]


class FollowupRule(FixtureModel):
    topic: StrictStr
    intent_hints: tuple[StrictStr, ...]
    requires_documents: bool
    match_any: tuple[StrictStr, ...] = ()
    en: StrictStr


class DocumentGuidance(FixtureModel):
    default_guidance: dict[str, StrictStr]
    case_type_guidance: dict[str, dict[str, StrictStr]]
    document_guidance: dict[str, dict[str, StrictStr]]
    document_alternative_guidance: dict[str, dict[str, StrictStr]]
    claim_followup_settings: dict[str, dict[str, StrictStr]]
    claim_followup_guidance: tuple[FollowupRule, ...]
    claim_followup_fallback: dict[str, StrictStr]


class Fixtures(FixtureModel):
    policyholders: tuple[Policyholder, ...]
    claims: tuple[ClaimRecord, ...]
    representatives: tuple[Representative, ...]
    claim_schema: ClaimSchema
    consent_scenarios: dict[str, ConsentScenario]
    required_document_guideline: DocumentGuidance


def load_fixtures(directory: Path = FIXTURES) -> Fixtures:
    documents = {}
    for name in Fixtures.model_fields:
        path = directory / f"{name}.json"
        try:
            documents[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"{path.name}: {error}") from error
    try:
        fixtures = Fixtures.model_validate(documents)
    except ValidationError as error:
        raise ValueError(f"Invalid fixture fields: {error.errors(include_input=False)}") from error
    for label, values in (
        ("policyholders.party_id", [row.party_id for row in fixtures.policyholders]),
        ("policyholders.policy_number", [row.policy_number for row in fixtures.policyholders]),
        ("claims.case_id", [row.case_id for row in fixtures.claims]),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"{label}: duplicate identifier")
    parties = {row.party_id for row in fixtures.policyholders}
    for claim in fixtures.claims:
        if claim.party_id not in parties:
            raise ValueError(f"claims: {claim.case_id} references an unknown party")
    for representative in fixtures.representatives:
        if representative.buyer_party_id not in parties:
            raise ValueError("representatives: unknown buyer_party_id")
    return fixtures
