from dataclasses import replace
from contextlib import closing
from datetime import date
import json

from pydantic import ValidationError
import pytest
import yaml

from apps.insurance_claims.database import (
    AccessDenied,
    ClaimFilters,
    FIXTURES,
    SQLiteClaimRepository,
    SQLiteCustomerRepository,
    SQLiteDatabase,
    SQLiteKnowledgeRepository,
    seed_database,
)
from apps.insurance_claims.identity import CallerEligibility, IdentitySubmission, IdentityVerification
from apps.insurance_claims.sop import Phase, SOPMachine, WorkflowState, load_sop
from apps.insurance_claims.tools import ClaimToolGateway


MARGARET = {
    "full_name": "Margaret Chen",
    "date_of_birth": "1985-03-15",
    "ssn_last4": "4472",
    "policy_id": "POL-9921",
    "caller_role": "policyholder",
}


@pytest.fixture
def database(tmp_path):
    database = SQLiteDatabase(tmp_path / "demo.sqlite3")
    seed_database(database)
    seed_database(database)
    return database


@pytest.fixture
def foundation(database):
    verifier = IdentityVerification(SQLiteCustomerRepository(database))
    return SOPMachine(load_sop()), verifier, SQLiteClaimRepository(database)


def test_three_fields_in_one_turn(foundation):
    machine, verifier, _ = foundation
    state = machine.submit_identity(WorkflowState(), IdentitySubmission(**MARGARET), verifier)
    assert state.identity_verified
    assert state.identity.party_id == "P9"
    assert state.phase == Phase.RESOLVE_INTENT
    assert state.collected == IdentitySubmission()


def test_accumulates_across_turns(foundation):
    machine, verifier, _ = foundation
    state = WorkflowState()
    for turn in [
        {"full_name": "  MARGARET  Chen ", "caller_role": "policyholder"},
        {"phone": "(650) 521-2836"},
        {"email": "MARGARET@email.com"},
    ]:
        assert state.phase == Phase.VERIFY_ID
        state = machine.submit_identity(state, IdentitySubmission(**turn), verifier)
    assert state.identity_verified
    assert state.phase == Phase.RESOLVE_INTENT


@pytest.mark.parametrize("changes", [
    {"ssn_last4": None},
    {"ssn_last4": "0000"},
    {"policy_id": "POL-1044"},
    {"caller_role": "representative"},
    {"email": "ava.lopez@email.com"},
])
def test_incomplete_conflicting_or_ineligible_submission(foundation, changes):
    machine, verifier, _ = foundation
    state = machine.submit_identity(
        WorkflowState(), IdentitySubmission(**(MARGARET | changes)), verifier
    )
    assert not state.identity_verified
    assert state.phase == Phase.VERIFY_ID


def test_repeating_one_field_does_not_verify(foundation):
    machine, verifier, _ = foundation
    state = WorkflowState()
    turn = IdentitySubmission(full_name="Margaret Chen", policy_id="POL-9921", caller_role="policyholder")
    for _ in range(3):
        state = machine.submit_identity(state, turn, verifier)
    assert not state.identity_verified
    assert state.phase == Phase.VERIFY_ID


def test_ssn_is_a_string_and_preserves_leading_zeros():
    assert IdentitySubmission(ssn_last4="0042").ssn_last4 == "0042"
    with pytest.raises(ValidationError):
        IdentitySubmission(ssn_last4=42)


def test_gateway_and_repository_block_unverified_access(foundation):
    _, _, claims = foundation
    gateway = ClaimToolGateway(claims)
    for state in [WorkflowState(), WorkflowState(phase=Phase.PROCESS_CASE)]:
        with pytest.raises(AccessDenied):
            gateway.get_claim(state, "CL-2048")
        with pytest.raises(AccessDenied):
            gateway.search_claims(state)
    with pytest.raises(AccessDenied):
        claims.get_owned(None, "CL-2048")
    with pytest.raises(AccessDenied):
        claims.list_owned(None)


def test_verified_claim_access_is_owner_scoped(foundation):
    machine, verifier, claims = foundation
    state = machine.submit_identity(WorkflowState(), IdentitySubmission(**MARGARET), verifier)
    gateway = ClaimToolGateway(claims)
    owned = gateway.search_claims(state)
    raw = json.loads((FIXTURES / "claims.json").read_text(encoding="utf-8"))
    assert {claim.case_id: claim.details for claim in owned} == {
        row["case_id"]: row for row in raw if row["party_id"] == "P9"
    }
    for claim in owned:
        assert claim.party_id == "P9"
        assert claim.policy_id == "POL-9921"
        assert claim.created_at == date.fromisoformat(claim.details["created_at"])
    january = ClaimFilters(case_type="healthcare", month=1)
    assert [claim.case_id for claim in gateway.search_claims(state, january)] == ["CL-2011", "CL-2048"]
    for filters in [
        ClaimFilters(case_type="healthcare", month=1, status="denied"),
        ClaimFilters(case_type="healthcare", month=1, year=2026),
    ]:
        assert [claim.case_id for claim in gateway.search_claims(state, filters)] == ["CL-2048"]
    assert gateway.search_claims(state, ClaimFilters(month=3, status="denied")) == []
    assert gateway.get_claim(state, "CL-2048").status == "denied"
    with pytest.raises(AccessDenied):
        gateway.get_claim(state, "CL-3001")
    with pytest.raises(AccessDenied):
        claims.get_owned(state.identity, "CL-3001")


def test_fixture_aliases_and_id_types(foundation, database):
    machine, verifier, _ = foundation
    customers = SQLiteCustomerRepository(database)
    fixture = json.loads((FIXTURES / "policyholders.json").read_text(encoding="utf-8"))
    for row in fixture:
        customer, = customers.candidates(row["policy_number"])
        assert customer.party_id == row["party_id"]
        assert customer.fields.date_of_birth == date.fromisoformat(row["dob"])
        assert customer.fields.ssn_last4 == (
            row["id_last4"] if row["id_type"] == "ssn_last4" else None
        )
        assert customer.aliases == {
            "full_name": row.get("name_aliases", []),
            "phone": row.get("phone_aliases", []),
            "email": row.get("email_aliases", []),
        }
    alias_submission = {
        "full_name": "Yaven Li",
        "phone": "+16505212830",
        "email": "yawen.li@example.com",
        "policy_id": "POL-7742",
        "caller_role": "policyholder",
    }
    state = machine.submit_identity(WorkflowState(), IdentitySubmission(**alias_submission), verifier)
    assert state.identity.party_id == "P13"
    state = machine.submit_identity(
        WorkflowState(),
        IdentitySubmission(**(alias_submission | {"phone": None, "ssn_last4": "5317"})),
        verifier,
    )
    assert not state.identity_verified


def test_representative_relationship_is_policy_scoped_and_requires_review(foundation):
    machine, verifier, claims = foundation
    representative = IdentitySubmission(**(MARGARET | {
        "caller_role": "representative",
        "representative_name": " DAVID  Chen ",
        "relationship": "SON",
    }))
    assert verifier.caller_eligibility(representative) == CallerEligibility.REPRESENTATIVE_REVIEW_REQUIRED
    for changes in [{"policy_id": "POL-1044"}, {"relationship": "brother"}, {"representative_name": "Ava Lopez"}]:
        assert verifier.caller_eligibility(
            representative.model_copy(update=changes)
        ) == CallerEligibility.UNCONFIRMED
    state = machine.submit_identity(WorkflowState(), representative, verifier)
    assert state.phase == Phase.VERIFY_ID
    with pytest.raises(AccessDenied):
        ClaimToolGateway(claims).search_claims(state)


def test_knowledge_matches_base_json(database):
    knowledge = SQLiteKnowledgeRepository(database)
    for name, data in [
        ("claim_schema", knowledge.claim_schema()),
        ("required_document_guideline", knowledge.required_document_guideline()),
    ]:
        assert data == json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    scenarios = json.loads((FIXTURES / "consent_scenarios.json").read_text(encoding="utf-8"))
    for name, scenario in scenarios.items():
        assert knowledge.consent_status_sequence(name) == tuple(scenario["status_sequence"])
    with pytest.raises(KeyError):
        knowledge.consent_status_sequence("unknown")


def test_reseed_reconciles_existing_demo_policy_and_claim(database):
    with closing(database.connect()) as connection, connection:
        connection.execute("INSERT INTO policies VALUES ('POL-9922', 'P9')")
        connection.execute(
            "UPDATE claims SET policy_id = 'POL-9922', details = '{}' WHERE case_id = 'CL-2102'"
        )
    seed_database(database)
    with closing(database.connect()) as connection:
        assert connection.execute("SELECT 1 FROM policies WHERE policy_id = 'POL-9922'").fetchone() is None
        row = connection.execute(
            "SELECT policy_id, details FROM claims WHERE case_id = 'CL-2102'"
        ).fetchone()
    assert row["policy_id"] == "POL-9921"
    assert json.loads(row["details"])["net_pay"] == "0.00"


def test_phase_order_and_guards(foundation):
    machine, verifier, _ = foundation
    state = WorkflowState()
    assert machine.advance(state) is state
    state = machine.submit_identity(state, IdentitySubmission(**MARGARET), verifier)
    assert machine.advance(state) is state
    state = machine.advance(replace(state, intent_resolved=True))
    assert state.phase == Phase.PROCESS_CASE
    assert machine.advance(state) is state
    state = machine.advance(replace(state, case_processed=True))
    assert state.phase == Phase.POST_PROCESS
    assert machine.advance(state) is state


def test_yaml_accepts_only_registered_guard_names(tmp_path):
    config = load_sop().model_dump(mode="json")
    config["transitions"][0]["guards"].append("identity_verified or True")
    path = tmp_path / "sop.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown SOP guards"):
        SOPMachine(load_sop(path))


def test_yaml_cannot_remove_required_verification_guard(tmp_path):
    config = load_sop().model_dump(mode="json")
    config["transitions"][0]["guards"] = []
    path = tmp_path / "sop.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid transition"):
        SOPMachine(load_sop(path))
