from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from fastapi.testclient import TestClient

from apps.insurance_claims.api import create_app
from apps.insurance_claims.settings import Settings


OPENING = ("I'm the policyholder. My name is Margaret Chen, policy POL-9921. "
           "I'm calling about my denied healthcare claim from January. "
           "DOB is 1985-03-15, SSN last four is 4472.")


def make_app(tmp_path, **overrides):
    return create_app(Settings(_env_file=None, database_url="sqlite:///" + str(tmp_path / "ui.db"),
                               llm_provider="mock", demo_diagnostics_key="test-key", **overrides))


def create_session(client):
    data = client.post("/api/v1/sessions").json()
    return f"/api/v1/sessions/{data['session_id']}", {"Authorization": f"Bearer {data['credential']}"}


def send(client, path, headers, text, key):
    return client.post(path + "/messages", headers=headers, json={"message_id": key, "message": text})


def test_workspace_and_diagnostics_are_independently_authorized(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        path, headers = create_session(client)
        other_path, _ = create_session(client)
        assert client.get(path + "/workspace").status_code == 404
        assert client.get(other_path + "/workspace", headers=headers).status_code == 404
        assert client.get(path + "/events", headers=headers).status_code == 404
        assert client.get(path + "/workspace", headers=headers).json()["claim"] is None
        assert send(client, path, headers, OPENING, "identity").json()["phase"] == "PROCESS_CASE"
        assert client.get(path + "/workspace", headers=headers).json()["claim"]["case_id"] == "CL-2048"
        response = client.get(path + "/events", headers=headers | {"X-Demo-Key": "test-key"})
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] == 3
        assert data["origin_phases"]["claim_hints.month"] == "VERIFY_ID"
        assert "Margaret" not in response.text and "margaret@email.com" not in response.text
        assert [e["action"] for e in data["events"] if e["event_type"] == "phase_transition"] == [
            "RESOLVE_INTENT", "PROCESS_CASE",
        ]


def test_versioned_mock_summary_replays_once_and_rejects_conflicts(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        path, headers = create_session(client)
        assert client.post(path + "/summary", headers=headers,
                           json={"choice": "send", "revision": "false"}).status_code == 409
        send(client, path, headers, OPENING, "identity")
        send(client, path, headers, "That's everything.", "finished")
        original = client.get(path + "/workspace", headers=headers).json()["summary"]
        assert original["recipient"] == "m***@email.com"
        send(client, path, headers, "What exactly is missing?", "followup")
        assert client.post(path + "/summary", headers=headers, json={
            "choice": "send", "revision": original["revision"],
        }).status_code == 409
        revision = client.get(path + "/workspace", headers=headers).json()["summary"]["revision"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post(path + "/summary", headers=headers, json={
                "choice": "send", "revision": revision,
            }), range(2)))
        assert [r.status_code for r in results] == [200, 200]
        result = client.get(path + "/workspace", headers=headers).json()
        assert result["summary"]["disposition"] == "simulated" and result["status"] == "completed"
        with closing(app.state.sessions.database.connect()) as connection:
            assert connection.execute("SELECT count(*) FROM summary_outcomes").fetchone()[0] == 1
        assert client.post(path + "/summary", headers=headers, json={
            "choice": "skip", "revision": revision,
        }).status_code == 409


def test_ambiguous_consent_then_natural_decline_produces_no_delivery(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        path, headers = create_session(client)
        send(client, path, headers, OPENING, "identity")
        send(client, path, headers, "That's everything.", "finished")
        assert send(client, path, headers, "Maybe later.", "ambiguous").json()["session_status"] == "active"
        assert send(client, path, headers, "Skip email.", "decline").json()["session_status"] == "completed"
        with closing(app.state.sessions.database.connect()) as connection:
            assert connection.execute(
                "SELECT count(*) FROM summary_outcomes WHERE disposition='simulated'"
            ).fetchone()[0] == 0
