from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import httpx
import pytest

from apps.insurance_claims.api import JSON_BODY_LIMIT, create_app
from apps.insurance_claims.claim_processing import DeadlineStatus, appeal_information
from apps.insurance_claims.conversation_models import ConversationAnalysis
from apps.insurance_claims.fixtures_loader import load_fixtures
from apps.insurance_claims.llm import ModelFailure, OpenAIProvider
from apps.insurance_claims.policy import TOOLS
from apps.insurance_claims.session import SessionUnavailable
from apps.insurance_claims.settings import Settings


FIXTURES = load_fixtures()
AUDIT_KEY = "local-test-operator"


@pytest.fixture
def app(tmp_path):
    settings = Settings(_env_file=None, llm_provider="mock", demo_diagnostics_key=AUDIT_KEY,
                        database_url=f"sqlite:///{tmp_path / 'audit.db'}")
    now = [datetime(2026, 11, 26, 18, tzinfo=timezone.utc)]
    return create_app(settings, clock=lambda: now[0]), now


def session(client):
    payload = client.post("/api/v1/sessions").json()
    return payload["session_id"], payload["credential"]


def headers(credentials):
    return {"Authorization": "Bearer " + credentials[1]}


def message(client, credentials, message_id, message_text):
    return client.post(f"/api/v1/sessions/{credentials[0]}/messages", headers=headers(credentials),
                       json={"message_id": message_id, "message": message_text})


def verify(client, credentials, party):
    user = next(item for item in FIXTURES.policyholders if item.party_id == party)
    result = message(client, credentials, "verify", (
        f"I'm the policyholder. My name is {user.name}, policy {user.policy_number}. "
        f"My phone is {user.phone}. My email is {user.email}."
    ))
    assert result.json()["phase"] == "RESOLVE_INTENT"


def test_json_contract_rejects_oversized_streams_and_redacts_errors(app):
    application, _ = app
    with TestClient(application) as client:
        credentials = session(client)
        path = f"/api/v1/sessions/{credentials[0]}/messages"
        credentials_headers = headers(credentials)
        media = client.post(path, headers={**credentials_headers, "Content-Type": "text/plain"},
                            content="synthetic text")
        assert media.status_code == 415
        broken = client.post(path, headers={**credentials_headers, "Content-Type": "application/json"},
                              content='{"message":"synthetic-private-canary"')
        assert broken.status_code == 422 and "synthetic-private-canary" not in broken.text
        def body():
            for _ in range(5):
                yield b"x" * (JSON_BODY_LIMIT // 4)
        too_large = client.post(path, headers={**credentials_headers, "Content-Type": "application/json"},
                                content=body())
        assert too_large.status_code == 413
        assert application.state.sessions.get(*credentials).version == 0


def claim_arguments(name, case_id):
    return {"case_id": case_id} | {
        "get_financial_field_definition": {"field": "net_pay"},
        "get_document_guidance": {"document": "pathology report"},
        "get_document_alternatives": {"document": "pathology report"},
        "get_claim_followup_guidance": {"topic": "submission_method"},
    }.get(name, {})


@pytest.mark.parametrize("name", [name for name, tool in TOOLS.items() if tool.owner])
def test_every_owner_tool_fails_closed_and_accepts_owned_scope(app, name):
    application, now = app
    with TestClient(application) as client:
        credentials = session(client)
        other = session(client)
        flow = application.state.workflow
        assert not flow.execute_tool(*credentials, name, claim_arguments(name, "CL-2048")).decision.allowed
        verify(client, credentials, "P9")
        verify(client, other, "P12")
        denied = flow.execute_tool(*credentials, name, claim_arguments(name, "CL-3001"))
        assert denied.output is None and denied.decision.reason == "ownership_required"
        assert flow.execute_tool(*credentials, name, claim_arguments(name, "CL-2048")).decision.allowed
        assert not flow.execute_tool(*other, name, claim_arguments(name, "CL-2048")).decision.allowed
        invalid = flow.execute_tool(*credentials, name, claim_arguments(name, "CL-2048") | {"party_id": "P12"})
        assert not invalid.decision.allowed and invalid.decision.reason == "invalid_arguments"
        now[0] += timedelta(minutes=31)
        with pytest.raises(SessionUnavailable):
            flow.execute_tool(*credentials, name, claim_arguments(name, "CL-2048"))


def test_exhausted_tool_budget_does_not_do_ownership_lookup(app, monkeypatch):
    application, _ = app
    with TestClient(application) as client:
        credentials = session(client)
        verify(client, credentials, "P9")
        def invalid_lookup(*args):
            pytest.fail("ownership lookup ran after budget was exhausted")
        monkeypatch.setattr(application.state.workflow.claims, "check_ownership", invalid_lookup)
        denied = application.state.workflow.execute_tool(*credentials, "get_claim_details",
                                                          {"case_id": "CL-2048"}, remaining=0)
        assert denied.decision.reason == "execution_limit" and denied.output is None


def test_seeded_claim_facts_match_all_fixture_records(app):
    application, _ = app
    with TestClient(application) as client:
        credentials = {party: session(client) for party in ("P9", "P12")}
        for party, current in credentials.items():
            verify(client, current, party)
        for claim in FIXTURES.claims:
            observed = application.state.workflow.execute_tool(
                *credentials[claim.party_id], "get_claim_details", {"case_id": claim.case_id},
            ).output
            assert observed == claim
            assert isinstance(observed.net_pay, Decimal)
            assert observed.model_dump(mode="json")["net_pay"] == format(claim.net_pay, ".2f")


@pytest.mark.parametrize("http_status,body,expected,transient", [
    (401, {}, "provider_credentials_invalid", False),
    (429, {}, "provider_unavailable", True),
    (503, {}, "provider_unavailable", True),
    (400, {}, "provider_request_rejected", False),
    (200, {"choices":[{"message":{"content":""}}]}, "model_empty", False),
    (200, {"choices":[{"message":{"content":"{"},"finish_reason":"length"}]}, "model_token_limit", False),
    (200, {"choices":[{"message":{"content":"not JSON"}}]}, "model_output_invalid", False),
    (200, {"choices":[{"message":{"content":"{}"}}],"usage":[{}]}, "model_output_invalid", False),
])
def test_provider_error_contract(http_status, body, expected, transient):
    transport = httpx.MockTransport(lambda _: httpx.Response(http_status, json=body))
    with httpx.Client(transport=transport) as client:
        provider = OpenAIProvider("synthetic-key", "synthetic-model", 1, client)
        with pytest.raises(ModelFailure) as error:
            provider.generate_structured([], ConversationAnalysis, temperature=0, max_tokens=100)
    assert (error.value.code, error.value.transient) == (expected, transient)


def test_malformed_usage_cannot_enter_telemetry():
    def response(_):
        return httpx.Response(200, json={
            "choices":[{"message":{"content":"{}"}}],
            "usage":{"prompt_tokens":"synthetic-canary","completion_tokens":-1},
        })
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        provider = OpenAIProvider("synthetic-key", "synthetic-model", 1, client)
        result = provider.generate_structured([], ConversationAnalysis, temperature=0, max_tokens=100)
    assert result.input_tokens is None and result.output_tokens is None


def test_mock_summary_replay_survives_restart(app):
    application, _ = app
    with TestClient(application) as client:
        credentials = session(client)
        verify(client, credentials, "P9")
        message(client, credentials, "claim", "Show me CL-2048.")
        message(client, credentials, "finish", "That's everything.")
        path = f"/api/v1/sessions/{credentials[0]}"
        view = client.get(path + "/workspace", headers=headers(credentials)).json()
        assert view["summary"]["actions"] == ["send", "skip"]
        payload = {"revision": view["summary"]["revision"], "choice": "send"}
        assert client.post(path + "/summary", headers=headers(credentials), json=payload).status_code == 200
    with TestClient(application) as client:
        assert client.post(path + "/summary", headers=headers(credentials), json=payload).status_code == 200
        events = client.get(path + "/events", headers=headers(credentials) | {"X-Demo-Key": AUDIT_KEY}).json()["events"]
        assert Counter(event["event_type"] for event in events)["email_delivery_simulated"] == 1
        with closing(application.state.sessions.database.connect()) as connection:
            assert connection.execute("SELECT count(*) FROM summary_outcomes").fetchone()[0] == 1


@pytest.mark.parametrize("case_id, deadline", [("CL-2048", date(2026, 3, 18)), ("CL-3001", date(2026, 4, 15))])
def test_fixture_deadline_boundaries(case_id, deadline):
    claim = next(row for row in FIXTURES.claims if row.case_id == case_id)
    assert claim.appeal_deadline == deadline
    for days, status in [(-1, DeadlineStatus.UPCOMING), (0, DeadlineStatus.DUE_TODAY), (1, DeadlineStatus.PASSED)]:
        assert appeal_information(claim.appeal_deadline, deadline + timedelta(days=days)).status == status


def test_openapi_contract_and_public_docs_disabled(app):
    application, _ = app
    schema = application.openapi()
    assert {"get"} == set(schema["paths"]["/health"])
    path = "/api/v1/sessions/{session_id}"
    assert {"get"} == set(schema["paths"][path + "/events"])
    assert set(schema["components"]["schemas"]["ChatInput"]["properties"]) == {"message", "message_id"}
    assert schema["components"]["schemas"]["ChatInput"]["additionalProperties"] is False
    with TestClient(application) as client:
        assert client.get("/openapi.json").status_code == 404


def test_submission_method_paraphrase_survives_protected_projection(app):
    application, _ = app
    with TestClient(application) as client:
        credentials = session(client)
        verify(client, credentials, "P9")
        message(client, credentials, "claim", "Show me CL-2048.")
        result = message(client, credentials, "fax", "Can my doctor fax it?").json()["response"]
        assert "member portal" in result and "fax or mail" in result
