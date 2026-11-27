# Evaluation notes

The [README results table](../README.md#verification-results) summarizes the latest Docker, mock, live Gemini, and offline OpenAI evidence. These checks use synthetic data from the assessment starter. They measure observed behavior on the included scenarios.

## What was exercised on November 26, 2026

- **Hosted and Docker walkthrough.** The public Render gateway and the local Compose gateway reported mock mode. In a fresh conversation, name and DOB plus a policy number left the session in verification. A second request for the denial revealed no claim information. A later email supplied the third eligible factor, and the remembered January healthcare denial resolved to CL-2048. Grounded document guidance, summary send and skip in separate sessions, out-of-scope handoff, and SSN refusal with alternative fields passed. The summary preview included the denied status, topics and missing documents. Detailed replacement guidance remained in the chat. [Walkthrough](DEMO_GUIDE.md)
- **Docker persistence.** An earlier Windows Docker Desktop run kept one simulated send and one decline in the isolated SQLite volume after a backend restart. The later reviewer run rebuilt and started both containers and repeated the gateway walkthrough. Render's free service has temporary session storage. [Deployment instructions](DEPLOYMENT.md)
- **Backend and browser coverage.** The reviewer backend rerun passed 109 tests with three opt-in live tests skipped. Earlier recorded frontend checks passed TypeScript, three unit tests and ten Chromium tests. The suite covers all 11 owner-scoped tools, representative review, expiry, stale summary revisions, concurrent consent, replay after restart, and browser session isolation. [Backend tests](../tests/) | [Browser tests](../frontend/e2e/)
- **Model checks.** The full Gemini run used `gemini-3.1-flash-lite`, one model analysis pass per turn, deterministic evidence rendering, a 6.2-second minimum request interval, one allowed retry and a 15-second timeout. It recorded 47 successful HTTP responses and four retryable HTTP 503 responses. The later focused Margaret send run passed with two successful Gemini analysis calls. The OpenAI contract tests use mocked HTTP. [Full Gemini report](../evaluation/reports/gemini_live_final_status.json) | [OpenAI adapter tests](../tests/test_phase3.py)

## Useful findings

- Clear case-status wording and remembered hints are useful when a model leaves a field blank. The code preserves a supported stored intent when a model returns an unknown intent. Phase 10 also found that direct provider submission questions could return formatting guidance. The fix selects the approved direct-submission text for the document when available. [Regression tests](../tests/test_phase4.py)
- Exploratory checks found that vague references to another claim, misspellings, and some document or statement paraphrases could need clarification. The evaluated scenarios are a small sample. The earlier live Gemini run recorded failures before the schema and routing fixes. [Earlier Gemini report](../evaluation/reports/gemini_live_schema_status.json)
- Browser tests observed a Next.js warning about the test startup command. The separate production standalone server passed the native smoke test. Broader browser and accessibility verification was outside those checks.
- A previous npm audit reported zero advisories and `pip check` passed. A Python vulnerability scanner was unavailable. Production identity proofing, medical data use, real email, and live human dispatch are outside this prototype. [Security notes](SECURITY_AUDIT.md)

## Reproduce and inspect

From an installed project environment, run `python -m pytest -q`, `python -m evaluation.run --provider mock`, or `python -m evaluation.run --provider configured --scenario MARGARET_SEND`. The configured check needs a backend model and a key. Use only synthetic inputs.

The runner records scenario IDs, check counts, dispositions and timing. It does not record raw identity inputs in the reports. For the dataset and older timing measurements, see the [scenario dataset](../evaluation/datasets/insurance_sop_scenarios.jsonl), [mock results](../evaluation/reports/phase11_deterministic.json), and [earlier mock timings](../evaluation/reports/phase9_deterministic.json).
