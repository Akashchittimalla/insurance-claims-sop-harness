from dataclasses import dataclass
from datetime import date
from enum import Enum
import re
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints


class IdentityFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    full_name: StrictStr | None = None
    date_of_birth: date | None = None
    phone: StrictStr | None = None
    email: StrictStr | None = None
    ssn_last4: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]{4}$")] | None = None


class CallerRelationship(str, Enum):
    POLICYHOLDER = "policyholder"
    REPRESENTATIVE = "representative"
    OTHER = "other"


class IdentitySubmission(IdentityFields):
    policy_id: StrictStr | None = None
    caller_role: CallerRelationship | None = None
    representative_name: StrictStr | None = None
    relationship: StrictStr | None = None


class CallerEligibility(str, Enum):
    POLICYHOLDER = "policyholder"
    REPRESENTATIVE_REVIEW_REQUIRED = "representative_review_required"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class Customer:
    party_id: str
    fields: IdentityFields
    aliases: dict[str, list[str]]


@dataclass(frozen=True)
class VerifiedIdentity:
    """Backend-only result issued by IdentityVerification after matching."""

    party_id: str
    matched_fields: frozenset[str] = frozenset()


class PolicyholderRepository(Protocol):
    def candidates(self, policy_id: str | None) -> list[Customer]: ...


class RepresentativeRepository(Protocol):
    def represented_party(self, policy_id: str, name: str, relationship: str) -> str | None: ...


class CustomerRepository(PolicyholderRepository, RepresentativeRepository, Protocol):
    pass


def normalize(field: str, value: str) -> str:
    if field == "full_name":
        return " ".join(value.casefold().split())
    if field == "email":
        return value.strip().casefold()
    if field == "phone":
        if not re.fullmatch(r"[+0-9().\s-]+", value):
            return ""
        digits = re.sub(r"[^0-9]", "", value)
        if len(digits) == 11 and digits.startswith("1"):
            return digits[1:]
        return digits
    return value


class IdentityVerification:
    def __init__(self, customers: CustomerRepository, minimum_fields: int = 3):
        if not 3 <= minimum_fields <= 5:
            raise ValueError("verification requires three to five distinct fields")
        self._customers = customers
        self.minimum_fields = minimum_fields

    def caller_eligibility(self, submission: IdentitySubmission) -> CallerEligibility:
        if submission.caller_role == "policyholder":
            if submission.representative_name is None and submission.relationship is None:
                return CallerEligibility.POLICYHOLDER
        if self.represented_party(submission) is not None:
            return CallerEligibility.REPRESENTATIVE_REVIEW_REQUIRED
        return CallerEligibility.UNCONFIRMED

    def represented_party(self, submission: IdentitySubmission) -> str | None:
        if (
            submission.caller_role == "representative"
            and submission.policy_id
            and submission.representative_name
            and submission.relationship
        ):
            return self._customers.represented_party(
                submission.policy_id.strip().upper(),
                normalize("full_name", submission.representative_name),
                normalize("full_name", submission.relationship),
            )
        return None

    def submit(
        self, prior: IdentitySubmission, turn: IdentitySubmission
    ) -> tuple[IdentitySubmission, VerifiedIdentity | None]:
        collected = IdentitySubmission.model_validate(
            prior.model_dump() | turn.model_dump(exclude_none=True)
        )
        supplied = collected.model_dump(
            mode="json", exclude_none=True, include=set(IdentityFields.model_fields)
        )
        normalized = {field: normalize(field, value) for field, value in supplied.items()}
        if (
            self.caller_eligibility(collected) != CallerEligibility.POLICYHOLDER
            or len(normalized) < self.minimum_fields
            or "" in normalized.values()
        ):
            return collected, None

        policy_id = collected.policy_id
        candidates = self._customers.candidates(
            policy_id.strip().upper() if policy_id is not None else None
        )
        matching = []
        for customer in candidates:
            stored = customer.fields.model_dump(mode="json", exclude_none=True)
            if all(
                value in {
                    normalize(field, option)
                    for option in [stored.get(field, ""), *customer.aliases.get(field, [])]
                    if option
                }
                for field, value in normalized.items()
            ):
                matching.append(customer.party_id)
        if len(matching) == 1:
            return collected, VerifiedIdentity(matching[0], frozenset(normalized))
        return collected, None
