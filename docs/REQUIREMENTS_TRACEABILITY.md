# Requirements Traceability

Phase 8 audit of the local synthetic demo. PASS means the named behavior was exercised in the stated mode. PARTIAL means the implemented subset was verified. BLOCKED and NOT_TESTED identify prerequisites or evidence gaps. See [evaluation results](EVALUATION_REPORT.md) for test counts and [security findings](SECURITY_AUDIT.md) for residual risk.

| ID | Requirement | Implementation | Executed evidence | Status | Remaining issue |
| --- | --- | --- | --- | --- | --- |
| SOP-001 | Start in VERIFY_ID and advance in order | `sop.py`, `sop.yaml`, `workflow.py` | Foundation, Phase 2 guards and Margaret send/skip traces | PASS | — |
| SOP-002 | Keep model and client outside authoritative state | `conversation_models.py`, `policy.py`, `api.py` | Phase 3 protected-field rejection and Phase 8 API schema | PASS | — |
| SOP-003 | Resume eligible interruptions and close deterministically | `recovery.py`, `handoff.py`, `presentation.py` | Phase 5 lock/resume and Phase 7 completion | PASS | Live handoff remains separate |
| IDV-001 | Three distinct approved factors on one record | `identity.py` | Foundation and Phase 2 distinct/mismatch tests | PASS | Production proofing policy open |
| IDV-002 | Policy lookup, aliases and National ID policy | `identity.py`, `database.py` | Foundation wrong policy, alias and ID type tests | PASS | National ID excluded pending approval |
| IDV-003 | Partial identity, refusal, correction and lock | `workflow.py`, `recovery.py` | Phase 3 and 5 conversational tests and Chromium recovery | PASS | Partial raw values are process-local |
| AUTH-001 | Owner-only read tools and no protected access before verification | `policy.py`, `tools.py`, `database.py` | Phase 8 matrix exercises all 11 owner-scoped tools with valid and invalid sessions | PASS | — |
| AUTH-002 | Representative relationship alone grants no access | `identity.py`, `workflow.py` | Phase 2 and 5 fail-closed tests, Chromium representative case | PASS | Independent delegation policy unavailable |
| AUTH-003 | Bounded tools and sanitized denial telemetry | `workflow.py`, `policy.py` | Phase 8 proves no ownership lookup on exhausted budget | PASS | — |
| MEM-001 | Preserve unverified claims hints across turns, reuse without repetition | `session.py`, `conversation.py` | HINT_MEMORY and Phase 2/3 memory tests | PASS | — |
| MEM-002 | Isolate session memory and active case evidence | `session.py`, `claim_processing.py` | Phase 4 switch and Chromium isolation/refresh | PASS | — |
| LLM-001 | Provider independence and explicit mock or configured mode | `llm.py`, `settings.py` | Offline OpenAI contract, transient and permanent failure tests | PASS | Live model evaluated separately |
| LLM-002 | Configured real-model quality and token usage | `evaluation/run.py`, real-provider tests | Explicit NOT_EXECUTED artifact | BLOCKED | No model and credential configured |
| CLAIM-001 | Resolve unique, ambiguous, absent and unauthorized claims | `workflow.py`, `conversation.py` | Phase 2/4 resolution, Chromium ambiguity, claim runner | PASS | — |
| CLAIM-002 | Keep all five fixture facts and missing fields faithful | `fixtures_loader.py`, `database.py`, `claim_processing.py` | Phase 8 compares each owned record; Phase 4 missing monetary value | PASS | — |
| CLAIM-003 | Exact Decimal values and correct appeal dates | `claim_processing.py` | Phase 8 scalar fixture and both deadline boundary tests | PASS | Exact cutoff time and appeal exceptions are unconfirmed |
| DOC-001 | Approved guidance, alternatives, aliases and six topics | `claim_processing.py`, guideline fixture | Phase 4 and runner paraphrases for each topic | PASS | Exact receipt or upload outcome is unavailable |
| GUARD-001 | Reject irrelevant content and keep mixed insurance context | `recovery.py`, `conversation.py` | Phase 5 threshold/mixed tests and Chromium scope | PASS | Broader live-language evaluation open |
| GUARD-002 | Empathy, refusal alternatives and bounded escalation | `recovery.py`, `handoff.py` | Phase 5 and Chromium recovery | PASS | Handoff stays simulated |
| GUARD-003 | Keep model-generated facts and protected values outside replies | `conversation.py`, `protected_input.py`, `claim_processing.py` | Phase 3–5 fabricated output, redaction and prompt override tests | PASS | Finite tested cases only |
| CONSENT-001 | Separate purpose, party, expiry and timeout | `consent.py`, `workflow.py` | Phase 2 state/cancellation tests and Chromium timeout | PASS | Business use of simulated consent unresolved |
| EMAIL-001 | Authorize preview, explicit choice and registered recipient | `presentation.py`, `api.py` | Phase 7 stale revision/ambiguity and both Margaret traces | PASS | Recipient changes remain unsupported |
| EMAIL-002 | No duplicate simulated delivery across races and restart | `presentation.py`, `session.py` | Phase 7 race, Phase 8 repeat after restart, persisted row and audit counts | PASS | Real provider uncertain-outcome reconciliation is pending |
| EMAIL-003 | External delivery, cancellation after dispatch and unknown outcome | SQLite mock only | No external email executed | NOT_IMPLEMENTED | Requires an approved adapter and outbox |
| API-001 | Session bearer, expiration, safe errors and request size | `api.py`, `session.py` | Phase 2 and 7 session tests; Phase 8 media, byte limit and schema tests | PASS | General rate limiting and deployment perimeter open |
| UI-001 | Natural-language chat, authoritative phase, retry and safe rendering | `frontend/app/`, `frontend/lib/` | TypeScript/unit, mocked component and real Chromium | PASS | Cross-browser/assistive technology testing not executed |
| UI-002 | Diagnostics authorization, same-origin mutation and cookie privacy | `frontend/app/gateway/`, `api.py` | Phase 7 authorization and Chromium origin/HttpOnly checks | PASS | Production operator identity is out of current scope |
| UI-003 | Both summary choices and mobile layout | `frontend/app/page.tsx` | Chromium send, skip, ambiguity and small viewport | PASS | — |
| FIX-001 | Six valid and unchanged fixtures | `fixtures_loader.py` and six JSON files | Fixture tests and pre/post SHA-256 | PASS | — |
| DEPLOY-001 | Reproducible hosted or Docker delivery | [Deployment guide](DEPLOYMENT.md), separate runtime Dockerfiles, Compose and dependency locks | Official Compose parser, standalone native HTTP smoke and source archive | PARTIAL | Linux engine unavailable. Image builds, Compose startup and Compose volume persistence are unverified. |
