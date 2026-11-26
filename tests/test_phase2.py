from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from shutil import copytree

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from apps.insurance_claims.api import create_app
from apps.insurance_claims.consent import ConsentPurpose
from apps.insurance_claims.database import SQLiteDatabase, seed_database
from apps.insurance_claims.fixtures_loader import FIXTURES, ConsentStatus, load_fixtures
from apps.insurance_claims.session import Candidate, SessionStatus, SQLiteSessions, VerificationStatus
from apps.insurance_claims.settings import Settings
from apps.insurance_claims.sop import Phase
from apps.insurance_claims.workflow import FoundationWorkflow


MARGARET = {
    "caller_role": "policyholder", "full_name": "Margaret Chen",
    "date_of_birth": "1985-03-15", "ssn_last4": "4472", "policy_id": "POL-9921",
}
HINTS = {"case_type": "healthcare", "status": "denied", "month": 1}


@pytest.fixture
def setup(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'demo.db'}")
    db = SQLiteDatabase(settings.database_path)
    seed_database(db)
    clock = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    sessions = SQLiteSessions(db, settings.session_ttl_minutes, lambda: clock[0])
    sessions.initialize()
    return settings, sessions, FoundationWorkflow(sessions, settings), clock


def verified(sessions, flow):
    state, token = sessions.create()
    result = flow.run(state.session_id, token, Candidate(identity_candidates=MARGARET))
    assert result.state.phase == Phase.RESOLVE_INTENT
    return state.session_id, token


def test_fixture_validation_and_precision(tmp_path):
    fixtures = load_fixtures()
    assert (
        len(fixtures.policyholders), len(fixtures.claims), len(fixtures.representatives),
        len(fixtures.consent_scenarios), len(fixtures.claim_schema.field_descriptions),
        len(fixtures.required_document_guideline.claim_followup_guidance),
    ) == (4, 5, 1, 2, 4, 6)
    assert fixtures.claims[0].net_pay == Decimal("0.00")
    assert fixtures.claims[0].model_dump(mode="json")["net_pay"] == "0.00"
    copy = tmp_path / "fixtures"
    copytree(FIXTURES, copy)
    claims = copy / "claims.json"
    rows = json.loads(claims.read_text())
    claims.write_text(json.dumps(rows + rows[:1]))
    with pytest.raises(ValueError, match="duplicate identifier"):
        load_fixtures(copy)
    rows[0]["party_id"] = "invalid"
    claims.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="unknown party"):
        load_fixtures(copy)
    rows[0]["net_pay"] = 0.0
    claims.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="decimal string"):
        load_fixtures(copy)


def test_margaret_graph_waits_then_resolves_fixture_and_audits(setup):
    _, sessions, flow, _ = setup
    state, token = sessions.create()
    session_id = state.session_id
    assert state.phase == Phase.VERIFY_ID
    assert not flow.execute_tool(session_id, token, "get_claim_details", {"case_id": "CL-2048"}).decision.allowed
    turn = flow.run(session_id, token, Candidate(
        identity_candidates={"full_name": MARGARET["full_name"], "caller_role": "policyholder"},
        intent_hint="CLAIM_DENIAL", claim_hints=HINTS,
    ))
    assert turn.state.phase == Phase.VERIFY_ID
    assert turn.state.memory.provenance["claim_hints.month"] == 1
    turn = flow.run(session_id, token, Candidate(identity_candidates={
        key: value for key, value in MARGARET.items() if key not in {"full_name", "caller_role"}
    }))
    assert turn.state.phase == Phase.PROCESS_CASE
    assert turn.state.authorized_party_id == "P9"
    assert len(turn.state.matched_fields) == 3
    assert turn.state.resolved_case_id == "CL-2048"
    assert turn.state.claim_ownership_validated
    assert turn.state.memory.claim_hints.year is None
    detail = flow.execute_tool(session_id, token, "get_denial_reason", {"case_id": "CL-2048"})
    assert detail.output.denial_reason == load_fixtures().claims[0].denial_reason
    events = sessions.audit_events(session_id)
    transitions = [event.action for event in events if event.event_type == "phase_transition"]
    assert transitions == ["RESOLVE_INTENT", "PROCESS_CASE"]
    verified_at = next(i for i, event in enumerate(events) if event.event_type == "verification_succeeded")
    claim_at = next(i for i, event in enumerate(events) if event.action == "search_customer_claims")
    assert verified_at < claim_at
    with closing(sessions.database.connect()) as connection:
        raw_state = connection.execute("SELECT state FROM sessions").fetchone()[0]
    for secret in ("4472", "1985-03-15", "Margaret Chen", token):
        assert secret not in raw_state
        assert all(secret not in event.model_dump_json() for event in events)


def test_guards_recovery_and_tool_denials(setup):
    _, sessions, flow, _ = setup
    session_id, token = verified(sessions, flow)
    state = sessions.get(session_id, token)
    assert not flow.policy.can_transition(state, Phase.PROCESS_CASE)
    unresolved = state.model_copy(update={"resolved_intent": "CLAIM_DENIAL", "resolved_case_id": "CL-2048"})
    assert not flow.policy.can_transition(unresolved, Phase.PROCESS_CASE)
    assert flow.policy.apply_transition(state, Phase.POST_PROCESS) is state
    assert flow.execute_tool(session_id, token, "verify_identity", MARGARET).decision.reason == "invalid_phase"
    assert flow.execute_tool(session_id, token, "unrecognized", {}).decision.reason == "unknown_tool"
    assert flow.execute_tool(session_id, token, "get_claim_details", {}).decision.reason == "invalid_arguments"
    assert flow.execute_tool(session_id, token, "get_claim_details", {"case_id": "CL-3001"}).decision.reason == "ownership_required"
    turn = flow.run(session_id, token, Candidate(intent_hint="CLAIM_DENIAL",
                                                  claim_hints={"case_type": "healthcare", "month": 1}))
    assert turn.waiting_for == "claim_clarification"
    turn = flow.run(session_id, token, Candidate(claim_hints={"month": 7}))
    assert turn.waiting_for == "claim_not_found"
    turn = flow.run(session_id, token, Candidate(claim_hints=HINTS))
    assert turn.state.phase == Phase.PROCESS_CASE
    assert not flow.policy.can_transition(turn.state, Phase.POST_PROCESS)
    assert flow.finish_discussion(session_id, token).phase == Phase.POST_PROCESS
    assert flow.execute_tool(session_id, token, "send_email", {}).decision.reason == "explicit_consent_required"
    assert flow.skip_email(session_id, token).status == SessionStatus.COMPLETED


def test_lock_and_representative_handoff(setup):
    _, sessions, flow, _ = setup
    state, token = sessions.create()
    for _ in range(3):
        result = flow.run(state.session_id, token, Candidate(identity_candidates=MARGARET | {"ssn_last4": "0000"}))
    assert result.state.verification_attempts == 3
    assert result.state.verification == VerificationStatus.LOCKED
    assert result.state.status == SessionStatus.HANDOFF
    assert not flow.run(state.session_id, token, Candidate(identity_candidates=MARGARET)).state.identity_verified
    state, token = sessions.create()
    result = flow.run(state.session_id, token, Candidate(identity_candidates=MARGARET | {
        "caller_role": "representative", "representative_name": "David Chen", "relationship": "son",
    }))
    assert result.state.represented_party_id == "P9"
    assert result.state.status == SessionStatus.HANDOFF
    assert not result.state.identity_verified


def test_untrusted_state_and_hint_correction(setup):
    _, sessions, flow, _ = setup
    with pytest.raises(ValidationError):
        Candidate.model_validate({"identity_verified": True, "authorized_party_id": "P9"})
    state, token = sessions.create()
    result = flow.run(state.session_id, token, Candidate(intent_hint="CLAIM_DENIAL", claim_hints=HINTS))
    assert result.state.phase == Phase.VERIFY_ID
    result = flow.run(state.session_id, token, Candidate(claim_hints={"status": None}))
    assert result.state.memory.claim_hints.status is None
    assert result.state.memory.claim_hints.month == 1
    assert result.state.resolved_case_id is None


def test_consent_simulation_is_isolated_and_never_email_consent(setup):
    _, sessions, flow, _ = setup
    session_id, token = verified(sessions, flow)
    other_id, other_token = verified(sessions, flow)
    request = flow.start_consent(session_id, token, "default")
    assert request.status == ConsentStatus.PENDING
    arguments = {"request_id": request.request_id, "purpose": ConsentPurpose.SIMULATION}
    assert not flow.execute_tool(other_id, other_token, "get_consent_status", arguments).decision.allowed
    assert not flow.execute_tool(session_id, token, "get_consent_status", arguments | {
        "purpose": ConsentPurpose.REPRESENTATIVE_ACCESS,
    }).decision.allowed
    assert flow.execute_tool(session_id, token, "get_consent_status", arguments).output.status == ConsentStatus.PENDING
    assert flow.execute_tool(session_id, token, "get_consent_status", arguments).output.status == ConsentStatus.APPROVED
    assert not sessions.get(session_id, token).email_consent_granted
    timeout = flow.start_consent(session_id, token, "timeout")
    for poll in range(1, 6):
        output = flow.execute_tool(session_id, token, "get_consent_status", arguments | {
            "request_id": timeout.request_id,
        }).output
        assert output.poll_count == poll
    assert output.status == ConsentStatus.TIMED_OUT


def test_consent_cancel_and_expiration(setup):
    _, sessions, flow, clock = setup
    session_id, token = verified(sessions, flow)
    cancel = flow.start_consent(session_id, token, "default")
    with sessions.transaction() as connection:
        state = sessions.load(connection, session_id, token)
        result = flow.consent.update(connection, state, cancel.request_id, ConsentPurpose.SIMULATION,
                                     cancel=True)
    assert result.status == ConsentStatus.CANCELLED
    request = flow.start_consent(session_id, token, "default")
    clock[0] += timedelta(minutes=20)
    flow.run(session_id, token, Candidate())
    clock[0] += timedelta(minutes=11)
    result = flow.execute_tool(session_id, token, "get_consent_status", {
        "request_id": request.request_id, "purpose": "simulation",
    })
    assert result.output.status == ConsentStatus.EXPIRED


def test_foundation_api_projects_safe_state(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
        response = client.post("/api/v1/sessions")
        assert response.status_code == 201
        created = response.json()
        url = "/api/v1/sessions/" + created["session_id"]
        assert client.get(url).status_code == 404
        assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 404
        view = client.get(url, headers={"Authorization": "Bearer " + created["credential"]})
        assert view.json() == {k: v for k, v in created.items() if k != "credential"}
        assert view.json()["phase"] == "VERIFY_ID"


def test_environment_configuration_cannot_lower_security(monkeypatch):
    monkeypatch.setenv("MIN_VERIFICATION_FIELDS", "2")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("MIN_VERIFICATION_FIELDS", "3")
    monkeypatch.setenv("REDACT_PII", "false")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_expired_session_does_not_reveal_state(setup):
    from apps.insurance_claims.session import SessionUnavailable

    _, sessions, flow, clock = setup
    session_id, token = verified(sessions, flow)
    clock[0] += timedelta(minutes=30)
    with pytest.raises(SessionUnavailable):
        sessions.get(session_id, token)


def test_customer_without_claims_waits_for_input(setup):
    _, sessions, flow, _ = setup
    state, token = sessions.create()
    result = flow.run(state.session_id, token, Candidate(
        identity_candidates={
            "caller_role": "policyholder", "policy_id": "POL-7742",
            "full_name": "Yaven Li", "phone": "+16505212830", "email": "yawen.li@example.com",
        },
        intent_hint="CLAIM_DENIAL",
        claim_hints=HINTS,
    ))
    assert result.state.authorized_party_id == "P13"
    assert result.state.phase == Phase.RESOLVE_INTENT
    assert result.state.resolved_case_id is None
    assert result.waiting_for == "claim_not_found"
