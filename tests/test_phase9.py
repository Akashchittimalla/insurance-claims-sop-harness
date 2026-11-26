from fastapi.testclient import TestClient

from apps.insurance_claims.api import create_app
from apps.insurance_claims.settings import Settings


OPENING = ("I'm the policyholder. My name is Margaret Chen, policy POL-9921. "
           "I'm calling about my denied healthcare claim from January. "
           "DOB is 1985-03-15, SSN last four is 4472.")


def test_documented_completion_and_contextual_email_consent(tmp_path):
    settings = Settings(_env_file=None, llm_provider="mock",
                        database_url=f"sqlite:///{tmp_path / 'release.db'}")
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/sessions").json()
        path = f"/api/v1/sessions/{created['session_id']}"
        headers = {"Authorization": "Bearer " + created["credential"]}

        def send(key, message):
            return client.post(path + "/messages", headers=headers,
                               json={"message_id": key, "message": message}).json()

        assert send("early", "Yes, please send it.")["phase"] == "VERIFY_ID"
        assert send("verify", OPENING)["phase"] == "PROCESS_CASE"
        assert send("complete", "That's everything. Thank you.")["phase"] == "POST_PROCESS"
        assert send("unclear", "Send it.")["session_status"] == "active"
        assert send("accept", "Yes, please send it.")["session_status"] == "completed"
        view = client.get(path + "/workspace", headers=headers).json()
        assert view["summary"]["disposition"] == "simulated"
        assert send("accept", "Yes, please send it.")["session_status"] == "completed"
