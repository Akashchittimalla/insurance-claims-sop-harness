"""Verify the local same-origin deployment without printing credentials or raw inputs."""
import argparse
from http.cookiejar import CookieJar
import json
from time import perf_counter
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


OPENING = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. "
    "I'm calling about my denied healthcare claim from January. "
    "DOB is 1985-03-15, SSN last four is 4472."
)


def run_branch(base, consent):
    browser = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def call(path, body=None):
        headers = {"Accept": "application/json"}
        if body is not None:
            headers |= {"Origin": base, "Content-Type": "application/json"}
        request = Request(base + "/gateway/" + path, headers=headers,
                          data=None if body is None else json.dumps(body).encode())
        with browser.open(request, timeout=45) as response:
            return json.load(response)

    start = perf_counter()
    created = call("session", {})
    assert created["phase"] == "VERIFY_ID" and "credential" not in created
    assert call("workspace")["claim"] is None
    preauth = call("messages", {"message_id": "preauth", "message": "Tell me about CL-2048."})
    assert preauth["phase"] == "VERIFY_ID" and "pathology report" not in preauth["response"]

    prompts = [
        (OPENING, "pathology report"),
        ("What exactly is missing?", "office note"),
        ("What should I do if I cannot obtain the pathology report?", "replacement copy"),
        ("Can my doctor send the office note directly?", "provider can fax or upload the note directly"),
        ("How long does the review usually take?", "usually less than a week"),
        ("How much did insurance pay?", "USD 0.00"),
        ("What does the $1,450 amount represent?", "Allowed maximum"),
        ("Can I still appeal?", "2026-03-18"),
        ("That's everything. Thank you.", "completes our claim discussion"),
        ("Maybe later.", "skip email"),
    ]
    for index, (message, expected) in enumerate(prompts):
        result = call("messages", {"message_id": str(index), "message": message})
        assert expected in result["response"], f"{consent} step {index}: expected evidence missing"
    offer = call("workspace")
    assert offer["phase"] == "POST_PROCESS"
    assert offer["claim"]["case_id"] == "CL-2048"
    assert offer["summary"]["disposition"] == "pending"
    payload = {"message_id": "explicit-consent",
               "message": "Yes, please send me the summary." if consent == "send" else "Skip email."}
    final = call("messages", payload)
    assert final["session_status"] == "completed"
    assert call("messages", payload) == final
    completed = call("workspace")
    expected = "simulated" if consent == "send" else "declined"
    assert completed["summary"]["disposition"] == expected
    assert completed["summary"]["actions"] == []
    print(f"{consent}: CL-2048, completed, {expected}, {(perf_counter() - start) * 1000:.0f} ms")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    for choice in ("send", "skip"):
        run_branch(base, choice)


if __name__ == "__main__":
    main()
