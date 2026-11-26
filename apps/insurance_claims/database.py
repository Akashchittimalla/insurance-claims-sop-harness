import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .fixtures_loader import FIXTURES, load_fixtures
from .identity import Customer, IdentityFields, VerifiedIdentity, normalize


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    party_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL REFERENCES customers(party_id),
    UNIQUE (policy_id, party_id)
);
CREATE TABLE IF NOT EXISTS claims (
    case_id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    case_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT NOT NULL,
    FOREIGN KEY (policy_id, party_id) REFERENCES policies(policy_id, party_id)
);
CREATE INDEX IF NOT EXISTS claims_by_owner ON claims(party_id);
CREATE TABLE IF NOT EXISTS representatives (
    buyer_party_id TEXT NOT NULL REFERENCES customers(party_id),
    rep_name TEXT NOT NULL,
    relationship TEXT NOT NULL,
    profile TEXT NOT NULL,
    PRIMARY KEY (buyer_party_id, rep_name, relationship)
);
CREATE TABLE IF NOT EXISTS knowledge (
    name TEXT PRIMARY KEY,
    document TEXT NOT NULL
);
"""


class AccessDenied(PermissionError):
    """A protected resource is unavailable to the current caller."""


@dataclass(frozen=True)
class Claim:
    case_id: str
    party_id: str
    policy_id: str
    case_type: str
    created_at: date
    status: str
    details: dict


class ClaimFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_type: str | None = None
    case_id: str | None = None
    created_at: date | None = None
    status: str | None = None
    year: Annotated[int, Field(ge=1, le=9999)] | None = None
    month: Annotated[int, Field(ge=1, le=12)] | None = None


class SQLiteDatabase:
    def __init__(self, path: str | Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            connection.executescript(SCHEMA)


def seed_database(database: SQLiteDatabase) -> None:
    fixtures = load_fixtures(FIXTURES).model_dump(mode="json", exclude_unset=True)
    customers = fixtures["policyholders"]
    claims = fixtures["claims"]
    representatives = fixtures["representatives"]
    knowledge = {name: fixtures[name] for name in (
        "claim_schema", "required_document_guideline", "consent_scenarios"
    )}
    policies = {row["party_id"]: row["policy_number"] for row in customers}
    with closing(database.connect()) as connection:
        connection.executescript(SCHEMA)
        with connection:
            for customer in customers:
                connection.execute(
                    """INSERT INTO customers VALUES (?, ?)
                       ON CONFLICT(party_id) DO UPDATE SET profile = excluded.profile""",
                    (customer["party_id"], json.dumps(customer)),
                )
            connection.executemany(
                "INSERT INTO policies VALUES (?, ?) ON CONFLICT(policy_id) DO NOTHING",
                [(policy, party) for party, policy in policies.items()],
            )
            for claim in claims:
                connection.execute(
                    """INSERT INTO claims (case_id, party_id, policy_id, case_type, created_at, status, details)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(case_id) DO UPDATE SET
                           party_id = excluded.party_id, policy_id = excluded.policy_id,
                           case_type = excluded.case_type, created_at = excluded.created_at,
                           status = excluded.status, details = excluded.details""",
                    (
                        claim["case_id"], claim["party_id"],
                        policies[claim["party_id"]],
                        claim["case_type"], claim["created_at"], claim["status"], json.dumps(claim),
                    ),
                )
            # Remove the retired demo-only policy when upgrading an earlier seed.
            connection.execute(
                """DELETE FROM policies WHERE policy_id = 'POL-9922' AND party_id = 'P9'
                   AND NOT EXISTS (SELECT 1 FROM claims WHERE policy_id = policies.policy_id)"""
            )
            connection.execute("DELETE FROM representatives")
            connection.executemany(
                "INSERT INTO representatives VALUES (?, ?, ?, ?)",
                [
                    (
                        row["buyer_party_id"], normalize("full_name", row["rep_name"]),
                        normalize("full_name", row["relationship"]), json.dumps(row),
                    )
                    for row in representatives
                ],
            )
            connection.executemany(
                """INSERT INTO knowledge VALUES (?, ?)
                   ON CONFLICT(name) DO UPDATE SET document = excluded.document""",
                [(name, json.dumps(document)) for name, document in knowledge.items()],
            )


class SQLiteCustomerRepository:
    def __init__(self, database: SQLiteDatabase):
        self._database = database

    def registered_email(self, authorized_party_id: str) -> str | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT profile FROM customers WHERE party_id = ?", (authorized_party_id,)
            ).fetchone()
        return json.loads(row["profile"]).get("email") if row else None

    def represented_party(self, policy_id: str, name: str, relationship: str) -> str | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                """SELECT r.buyer_party_id FROM representatives AS r JOIN policies AS p
                   ON r.buyer_party_id = p.party_id
                   WHERE p.policy_id = ? AND r.rep_name = ? AND r.relationship = ?""",
                (policy_id, name, relationship),
            ).fetchone()
        return row["buyer_party_id"] if row is not None else None

    def candidates(self, policy_id: str | None) -> list[Customer]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """SELECT party_id, profile FROM customers
                   WHERE ? IS NULL OR party_id IN (
                       SELECT party_id FROM policies WHERE policy_id = ?
                   )""",
                (policy_id, policy_id),
            ).fetchall()
        customers = []
        for row in rows:
            profile = json.loads(row["profile"])
            customers.append(Customer(
                party_id=row["party_id"],
                fields=IdentityFields(
                    full_name=profile["name"], date_of_birth=profile["dob"],
                    phone=profile["phone"], email=profile["email"],
                    ssn_last4=profile["id_last4"] if profile["id_type"] == "ssn_last4" else None,
                ),
                aliases={
                    field: profile.get(f"{key}_aliases", [])
                    for field, key in (("full_name", "name"), ("phone", "phone"), ("email", "email"))
                },
            ))
        return customers


class SQLiteClaimRepository:
    def __init__(self, database: SQLiteDatabase):
        self._database = database

    def owns(self, identity: VerifiedIdentity, case_id: str) -> bool:
        if not isinstance(identity, VerifiedIdentity):
            return False
        with closing(self._database.connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM claims WHERE party_id = ? AND case_id = ?",
                (identity.party_id, case_id),
            ).fetchone() is not None

    def _owned(
        self, identity: VerifiedIdentity | None, case_id: str | None, filters: ClaimFilters
    ) -> list[Claim]:
        if not isinstance(identity, VerifiedIdentity):
            raise AccessDenied("Claim access denied")
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM claims WHERE party_id = :party_id
                   AND (:case_id IS NULL OR case_id = :case_id)
                   AND (:case_type IS NULL OR case_type = :case_type)
                   AND (:status IS NULL OR status = :status)
                   AND (:created_at IS NULL OR created_at = :created_at)
                   AND (:year IS NULL OR CAST(substr(created_at, 1, 4) AS INTEGER) = :year)
                   AND (:month IS NULL OR CAST(substr(created_at, 6, 2) AS INTEGER) = :month)
                   ORDER BY created_at, case_id""",
                {**filters.model_dump(mode="json"), "party_id": identity.party_id,
                 "case_id": case_id if case_id is not None else filters.case_id},
            ).fetchall()
        return [
            Claim(
                case_id=row["case_id"], party_id=row["party_id"],
                policy_id=row["policy_id"], case_type=row["case_type"],
                created_at=date.fromisoformat(row["created_at"]), status=row["status"],
                details=json.loads(row["details"]),
            )
            for row in rows
        ]

    def list_owned(
        self, identity: VerifiedIdentity | None, filters: ClaimFilters = ClaimFilters()
    ) -> list[Claim]:
        return self._owned(identity, None, filters)

    def get_owned(self, identity: VerifiedIdentity | None, case_id: str) -> Claim:
        if not case_id:
            raise AccessDenied("Claim access denied")
        claims = self._owned(identity, case_id, ClaimFilters())
        if not claims:
            raise AccessDenied("Claim access denied")
        return claims[0]


class SQLiteKnowledgeRepository:
    def __init__(self, database: SQLiteDatabase):
        self._database = database

    def _load(self, name: str) -> dict:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT document FROM knowledge WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise LookupError(f"Knowledge document is missing: {name}")
        return json.loads(row["document"])

    def claim_schema(self) -> dict:
        return self._load("claim_schema")

    def required_document_guideline(self) -> dict:
        return self._load("required_document_guideline")

    def consent_status_sequence(self, scenario: str) -> tuple[str, ...]:
        return tuple(self._load("consent_scenarios")[scenario]["status_sequence"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the synthetic claims demo database.")
    parser.add_argument("path", type=Path)
    seed_database(SQLiteDatabase(parser.parse_args().path))
