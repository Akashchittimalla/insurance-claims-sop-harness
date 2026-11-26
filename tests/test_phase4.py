from datetime import date, datetime, timezone
from contextlib import closing
import json
import os

from fastapi.testclient import TestClient
import pytest

from apps.insurance_claims.api import create_app
from apps.insurance_claims.claim_processing import DeadlineStatus, appeal_information
from apps.insurance_claims.conversation_models import GroundedResponse, mock_analysis
from apps.insurance_claims.llm import MockProvider
from apps.insurance_claims.settings import Settings


OPENING = ("I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about "
           "my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.")
STEPS = [
    (OPENING, ("denial reason", "pathology report", "office note")),
    ("What exactly is missing?", ("pathology report", "office note")),
    ("What should the pathology report contain?", ("specimen details", "testing date", "does not specify an original")),
    ("I don't have the original report. What can I do?", ("replacement copy", "acceptance is subject to review")),
    ("What about the office note?", ("visit date", "assessment")),
    ("How do I submit these?", ("member portal", "fax or mail")),
    ("How long will processing take after I submit them?", ("usually less than a week", "cannot be guaranteed")),
    ("How much did insurance actually pay?", ("USD 0.00",)),
    ("Then what is the $1,450 amount?", ("Allowed maximum", "Net fee", "USD 1450.00", "USD 0.00")),
    ("Can I still appeal?", ("2026-03-18", "has passed", "does not confirm appeal eligibility")),
    ("No, that's everything.", ("completes our claim discussion",)),
]


def settings(tmp_path, **options):
    return Settings(_env_file=None, database_url="sqlite:///" + str(tmp_path / "claims.db"), **options)


def open_session(client):
    data = client.post("/api/v1/sessions").json()
    return data["session_id"], data["credential"]


def chat(client, session, text, key):
    sid, credential = session
    result = client.post(f"/api/v1/sessions/{sid}/messages",
                         headers={"Authorization": f"Bearer {credential}"},
                         json={"message_id": str(key), "message": text})
    assert result.status_code == 200, result.text
    return result.json()


def main_dialogue(client, app):
    app.state.sessions.clock = lambda: datetime(2026, 11, 26, 18, tzinfo=timezone.utc)
    # Both session and interpretation use the injected clock.
    app.state.workflow.processing.clock = app.state.sessions.clock
    ss = open_session(client)
    for n, (question, expected) in enumerate(STEPS):
        result = chat(client, ss, question, n)
        assert all(term in result["response"] for term in expected), (n, result)
        assert result["phase"] == ("POST_PROCESS" if n == 10 else "PROCESS_CASE")
    state = app.state.sessions.get(*ss)
    assert state.resolved_case_id == "CL-2048"
    assert state.authorized_party_id == "P9"
    assert state.discussion_complete
    return ss


def test_complete_margaret_conversation(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = main_dialogue(client, app)
        events = app.state.sessions.audit_events(ss[0])
        assert [e.action for e in events if e.event_type == "phase_transition"] == [
            "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS",
        ]
        assert any(e.event_type == "evidence_retrieved" and e.action == "appeal_clock" for e in events)
        assert not any("4472" in e.model_dump_json(exclude={"event_id", "session_id"}) for e in events)


def test_direct_provider_submission_uses_document_guidance(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        session = open_session(client)
        chat(client, session, OPENING, "open")
        for index, question in enumerate((
            "Can my doctor send the office note directly?",
            "Could the clinic submit the office note for me?",
        )):
            result = chat(client, session, question, index)
            assert result["phase"] == "PROCESS_CASE"
            assert "provider can fax or upload the note directly" in result["response"]


@pytest.mark.parametrize("today,expected", [
    (date(2026, 3, 17), DeadlineStatus.UPCOMING),
    (date(2026, 3, 18), DeadlineStatus.DUE_TODAY),
    (date(2026, 3, 19), DeadlineStatus.PASSED),
])
def test_deadline_boundaries(today, expected):
    assert appeal_information(date(2026, 3, 18), today).status == expected
    assert appeal_information(None, today).status == DeadlineStatus.UNKNOWN


def test_switch_does_not_leak_old_evidence_or_expose_cross_customer_id(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = open_session(client)
        chat(client, ss, OPENING, 1)
        chat(client, ss, "What should the pathology report contain?", 2)
        auto = chat(client, ss, "What about my auto claim?", 3)
        assert "open" in auto["response"] and "pathology" not in auto["response"]
        state = app.state.sessions.get(*ss)
        assert state.resolved_case_id == "CL-2102" and state.discussion.document is None
        money = chat(client, ss, "What is the expected reimbursement?", 4)["response"]
        assert "USD 3200.00" in money and "USD 0.00" in money
        forbidden = chat(client, ss, "Show me CL-3001", 5)["response"]
        assert "diagnosis report" not in forbidden
        assert app.state.sessions.get(*ss).resolved_case_id == "CL-2102"


def test_pending_clarification_blocks_completion_and_reference_clears_it(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = open_session(client)
        chat(client, ss, OPENING, 1)
        ambiguous = chat(client, ss, "What should it contain?", 2)
        assert "Which document" in ambiguous["response"]
        assert chat(client, ss, "That's all I needed.", 3)["phase"] == "PROCESS_CASE"
        assert "specimen details" in chat(client, ss, "The pathology report.", 4)["response"]
        assert chat(client, ss, "That's everything.", 5)["phase"] == "POST_PROCESS"


def test_followup_rules_and_adversarial_draft(tmp_path):
    def fabricate(messages, schema):
        if schema is GroundedResponse:
            data = mock_analysis(messages, schema)
            data["response_text"] = "Your upload succeeded, we paid USD 900.00, and your appeal was extended."
            return data
        return mock_analysis(messages, schema)

    app = create_app(settings(tmp_path), MockProvider(fabricate))
    with TestClient(app) as client:
        ss = open_session(client)
        reply = chat(client, ss, OPENING, 1)["response"]
        assert "900" not in reply and "extended" not in reply and "succeeded" not in reply
        for i, (question, phrase) in enumerate([
            ("By when should I send everything?", "separate from any recorded appeal deadline"),
            ("Can I send a scanned PDF?", "clear, complete"),
            ("How can I check whether you received it?", "does not confirm whether the insurer received"),
        ], 2):
            assert phrase in chat(client, ss, question, i)["response"]
        assert any(e.event_type == "response_validation" and e.decision == "fallback"
                   for e in app.state.sessions.audit_events(ss[0]))


def test_multi_intent_budget_recovery_and_exhausted_alternatives(tmp_path):
    app = create_app(settings(tmp_path, max_tool_calls_per_turn=2))
    with TestClient(app) as client:
        ss = open_session(client)
        question = OPENING + " How much did insurance pay, and how do I send the missing documents?"
        initial = chat(client, ss, question, 1)
        assert initial["phase"] == "PROCESS_CASE" and "USD" not in initial["response"]
        state = app.state.sessions.get(*ss)
        assert len(state.discussion.pending_intents) >= 2
        assert chat(client, ss, "That's all I needed.", 2)["phase"] == "PROCESS_CASE"
        followup = chat(client, ss, "Please continue.", 3)["response"]
        assert "USD 0.00" in followup and "member portal" in followup and "denial reason" in followup
        exhausted = chat(client, ss, "I tried everything and have no alternatives.", 4)["response"]
        assert "human claims representative" in exhausted


def test_document_tools_owner_scope_and_general_auto_guidance(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = open_session(client)
        flow = app.state.workflow
        assert not flow.execute_tool(*ss, "get_document_guidance", {
            "case_id": "CL-2048", "document": "pathology report",
        }).decision.allowed
        chat(client, ss, OPENING, 1)
        denied = flow.execute_tool(*ss, "get_document_alternatives", {
            "case_id": "CL-3001", "document": "diagnosis report",
        })
        assert not denied.decision.allowed
        chat(client, ss, "What about my auto claim?", 2)
        guidance = chat(client, ss, "What should the repair estimate contain?", 3)["response"]
        assert "vehicle or claim reference" in guidance
        assert "does not list any required documents" in guidance
        assert "pathology" not in guidance


def test_closing_inquiry_does_not_update_claim_record(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = open_session(client)
        chat(client, ss, OPENING, 1)
        assert chat(client, ss, "That's everything.", 2)["phase"] == "POST_PROCESS"
        status = app.state.workflow.execute_tool(*ss, "get_claim_status", {"case_id": "CL-2048"})
        assert status.output.status == "denied"


def test_unknown_document_and_unavailable_money(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ss = open_session(client)
        chat(client, ss, OPENING, 1)
        answer = chat(client, ss, "What should the ultrasound report contain?", 2)["response"]
        assert "No document-specific rule" in answer and "For medical claims" in answer
        with closing(app.state.sessions.database.connect()) as connection, connection:
            details = json.loads(connection.execute(
                "SELECT details FROM claims WHERE case_id = 'CL-2048'"
            ).fetchone()[0])
            del details["net_pay"]
            connection.execute("UPDATE claims SET details = ? WHERE case_id = 'CL-2048'",
                               (json.dumps(details),))
        answer = chat(client, ss, "How much did insurance pay?", 3)["response"]
        assert "Recorded payment is unavailable" in answer and "USD 0.00" not in answer


@pytest.mark.skipif(os.getenv("RUN_REAL_MODEL_EVAL") != "1", reason="live provider evaluation is opt-in")
def test_real_provider_grounded_margaret(tmp_path):
    config = Settings()
    if not config.llm_api_key.get_secret_value() or not config.llm_model:
        pytest.skip("OpenAI model and credentials are required")
    app = create_app(settings(tmp_path, llm_provider="openai", llm_api_key=config.llm_api_key,
                              llm_model=config.llm_model))
    with TestClient(app) as client:
        main_dialogue(client, app)
