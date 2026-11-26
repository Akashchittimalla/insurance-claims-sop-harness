# Phase 8 Evaluation Report

Phase 10 repeated the synthetic evaluation with 20/20 scenarios. See the [final review](FINAL_REVIEW.md) for exploratory findings and the independent runtime checks.

## Readiness

**READY_WITH_LIMITATIONS** for a local synthetic demo. The audited flow reaches end-of-session through either Margaret summary choice. No critical security failure was observed in the executed suites. No live model, external mail, live handoff, Python advisory scan, or production deployment was verified. Compose parsing and native standalone smoke passed during Phase 9. Docker engine verification remains pending.

## Method

Executed on 2026-11-26 using the existing Windows project virtual environment, in-process FastAPI with ephemeral SQLite, and installed Chromium against separate Next.js and Uvicorn servers. The deterministic application provider was `mock/deterministic`, with extraction temperature 0, response temperature 0.3, and a tool budget of 3. The isolated evaluation clock was fixed for appeal assertions. The dataset is `insurance-sop-v1` with SHA-256 `5250ccc3b1df16c34557d67250111bd069eab03f3ab99a5b6cddea78d3568cc0`. It draws synthetic identity values from the supplied fixtures. JSON artifacts record the exact configuration and sanitized step outcomes.

Metrics are counts of tagged turns whose declared checks all passed. A turn can contribute to multiple metrics. These are checks of sampled fixture behavior rather than estimates of general model accuracy. The consent metric checks the backend decision and recorded delivery disposition. Financial, deadline and ownership assertions come from deterministic evidence, with no model judging these gates.

## Baseline and final verification

| Command | Baseline | Final | Exit |
| --- | --- | --- | --- |
| `.\.venv\Scripts\python.exe -m pytest --collect-only -q` | 75 collected | 103 collected | 0 |
| `.\.venv\Scripts\python.exe -m pytest -q --tb=short` | 72 passed, 3 skipped | 100 passed, 3 skipped, 0 failed, no xfails or xpasses | 0 |
| `npm.cmd --prefix frontend run typecheck` | Passed | Passed | 0 |
| `npm.cmd --prefix frontend run test` | 3 passed | 3 passed | 0 |
| `npm.cmd --prefix frontend run build` | Passed | Passed | 0 |
| `npm.cmd --prefix frontend run test:e2e` | 8 passed | 10 passed, including one mocked component test | 0 |
| `.\.venv\Scripts\python.exe -m pip check` | Passed | Passed | 0 |
| `npm.cmd --prefix frontend audit --json` | — | Zero reported advisories | 0 |

The backend suite covers unit rules, API contracts, repository integration, provider faults, malicious output rejection, concurrency, and restart replay. Three opt-in live tests were skipped. Public OpenAPI is disabled. The contract test uses the schema generated from the application object. Git status/diff, a configured coverage threshold, separate frontend lint and Python type-check scripts were unavailable. `pip-audit` was unavailable.

## Deterministic results

`evaluation.run --provider mock` completed **20 of 20 scenarios** on the final run. An initial harness startup failed before scenario evaluation because the demo key was passed as an untyped string. After correcting the harness, the first completed run passed 19 of 20 scenarios. The fax paraphrase failed because the privacy projection dropped the channel term. The correction retains approved generic channel words. The regression test and the repeated dataset run passed. See [deterministic_results.json](../evaluation/reports/deterministic_results.json).

| Tagged check | Passing/sample count | Percent | Failed IDs |
| --- | --- | --- | --- |
| appeal | 1/1 | 100% | — |
| claim resolution | 18/18 | 100% | — |
| completion | 3/3 | 100% | — |
| consent | 4/4 | 100% | — |
| financial | 3/3 | 100% | — |
| groundedness | 32/32 | 100% | — |
| identity | 18/18 | 100% | — |
| intent | 14/14 | 100% | — |
| memory | 3/3 | 100% | — |
| privacy | 5/5 | 100% | — |
| recovery | 6/6 | 100% | — |
| scope | 2/2 | 100% | — |
| sop | 21/21 | 100% | — |
| topics | 12/12 | 100% | — |

In the executed security cases, no unauthorized claim disclosure, authoritative transition, verification, representative access, cross-session disclosure, simulated delivery or exposed authentication credential was observed. The concurrency and restart tests observed zero duplicate logical mock deliveries. These counts apply to the executed cases only. Third-party email provider calls were zero because delivery is SQLite-only.

## Margaret execution traces

Both branches started at VERIFY_ID, matched three factors, advanced through RESOLVE_INTENT, and resolved CL-2048 in PROCESS_CASE with the fixture denial and outstanding documents. Both reached POST_PROCESS through the trusted completion guard.

| Scenario | Final phase and disposition | Authorized tools recorded | Simulated deliveries |
| --- | --- | --- | --- |
| MARGARET_SEND | POST_PROCESS, completed, simulated | 4 | 1 |
| MARGARET_SKIP | POST_PROCESS, completed, declined | 3 | 0 |
| MARGARET_AMBIGUOUS_CONSENT | Pending after the ambiguous reply, then completed on skip | 3 | 0 |

The alternate path kept the claim status unchanged. A valid claim reference attached to an invented reply does not authorize its contents. The test suite checks rejection of manufactured financial, upload, deadline and delivery claims.

## Performance

Local sequential API calls through TestClient, in milliseconds. These results exclude browser and external-network latency. Verification-turn counts include complete fixture identity turns, tool measurements cover approved internal operations, and summary choice timing includes the SQLite mock outcome transaction. Mock model values are provider placeholders. Live inference and token usage were not sampled.

| Operation | Samples | Min | p50 | p95 | Max |
| --- | --- | --- | --- | --- | --- |
| `api.chat_turn` | 37 | 14.582 | 31.112 | 45.217 | 45.807 |
| `api.events` | 56 | 6.74 | 9.193 | 11.815 | 12.462 |
| `api.session` | 20 | 12.058 | 13.954 | 19.769 | 24.649 |
| `api.summary_choice` | 3 | 24.339 | 25.191 | 26.027 | 26.027 |
| `api.summary_preview` | 3 | 17.987 | 18.473 | 18.548 | 18.548 |
| `api.verification_turn` | 16 | 32.699 | 47.168 | 86.231 | 86.231 |
| `api.workspace` | 56 | 6.774 | 11.494 | 19.09 | 21.361 |
| `knowledge.document_guidance` | 36 | 1.175 | 2 | 3.237 | 4.171 |
| `model.ConversationAnalysis` | 48 | 0 | 0 | 0 | 0 |
| `model.GroundedResponse` | 36 | 0 | 0 | 0 | 0 |
| `tool.get_claim_details` | 36 | 4.724 | 6.948 | 8.149 | 9.998 |
| `tool.search_customer_claims` | 19 | 1.759 | 2.84 | 4.457 | 4.457 |
| `tool.verify_identity` | 20 | 0.216 | 2.981 | 4.813 | 5.947 |

SQLite trace instrumentation counted operation prefixes only, without recording SQL text or values. Counts include startup and diagnostic reads. BEGIN 193, COMMIT 193, CREATE 17, DELETE 19, INSERT 653, SELECT 739, UPDATE 92.

## Conversational quality rubric

Apply the rubric to opt-in human review. Scores 2 and 4 are intermediate. This audit does not assign subjective live-model scores.

| Dimension | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Naturalness | Repetitive or incoherent | Understandable, formulaic | Concise and context-aware |
| Empathy | Dismissive | Appropriate acknowledgment | Specific acknowledgment and useful next step |
| Continuity | Repeats or loses known information | Retains most relevant context | Reuses relevant context accurately |
| Helpfulness | Misses supported request | Offers partial help | Completes the supported grounded request |
| Groundedness | Unsupported critical facts | Mostly supported with omissions | Every assessed fact is supported |
| Recovery | Bypass or persistent loop | Requirements preserved | Safe continuation, alternatives, or escalation |

## Live mode and delivery prerequisites

Live evaluation status is **NOT_EXECUTED** because no real model and credential were configured. See [real_model_status.json](../evaluation/reports/real_model_status.json). The verified runner accepts `--provider configured` after a model and key are configured in the environment. It supports `--scenario`, `--category`, and `--output`. It never uses live customer data or real mail. Live acceptance targets in the phase brief remain unmeasured.

Phase 9 reran 20/20 synthetic scenarios with 37 chat turns measured at 27.228 ms p50 and 41.580 ms p95. This local run uses mock inference. Container build and runtime timings require a Linux Docker engine. See [Phase 9 machine-readable metrics](../evaluation/reports/phase9_deterministic.json) and the [submission checklist](SUBMISSION_CHECKLIST.md). Broader browser, accessibility and provider quality checks remain open. See the [security audit](SECURITY_AUDIT.md) and [traceability matrix](REQUIREMENTS_TRACEABILITY.md).
