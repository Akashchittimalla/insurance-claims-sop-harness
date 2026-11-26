# Independent technical review

**NOT_READY for final submission. Internal score 80/100.** The native synthetic demo is operational. Two mandatory evidence gates remain open. The review host cannot run Docker containers, and real-model inference was unavailable. The score is an internal engineering assessment.

## Assignment coverage

| Original requirements | Assessment and evidence |
| --- | --- |
| 1 and 16. Natural-language agent and text interface | Operational through the React workspace, same-origin gateway and FastAPI. Browser and HTTP tests exercised real backend execution. Natural phrasing varies with the mock interpreter. |
| 2–4. Four phases, three factors, protected access | Verified. `sop.py`, `sop.yaml`, `workflow.py`, `identity.py`, `tools.py` and `database.py`. Distinct fields are checked against one eligible customer. Policy number narrows the lookup. The owner-tool matrix covers early and cross-owner denial. |
| 5 and 17. Flexible LLM reasoning and API-key access | OpenAI adapter and typed analysis and response calls exist. Offline HTTP contract passed. Live reasoning and output quality remain unverified. |
| 6–9. Memory, incomplete information, empathy, alternative identity | Partial candidates and hints carry forward. Approved alternative fields, corrections and refusal patterns have regression coverage. Unlabeled paraphrases and some frustration phrasing remain weak. National ID remains outside current policy. |
| 10–12. Refusal, scope and human assistance | Verified deterministic recovery, threshold offers and simulated handoff. Live routing is unavailable. |
| 13. Grounded claims | Verified owned-case reads, fixture denial reason, document guidance, Decimal amounts and the business-clock appeal response. |
| 14–15. Consent and send or skip | Verified explicit revision-bound choice and a single SQLite outcome. Decline completes without an email provider call. Send is a recorded simulation. |
| 18. Hosted or reproducible Docker delivery | Compose configuration previously passed the official parser. Native execution was reverified. No hosted instance or Docker engine runtime evidence. |

## Architecture and authority

The Next.js gateway owns browser credential transport and origin enforcement. The backend owns session and claim state. FastAPI routes for chat, workspace, diagnostics and summary choices delegate to deterministic code. LangGraph has six nodes in `workflow.py`. Two are waiting markers for processing and post-processing, whose real work lives in `conversation.py` and `presentation.py`. `Policy` applies named YAML guards, phase permissions and limits. The claim gateway repeats verification checks, and SQLite queries apply owner scope. `SessionState` is the durable authority, with a derived `WorkflowState` for policy evaluation.

The model receives a protected projection and returns structured proposals. It has no direct tool dispatch, phase write, verification write or summary completion path. Eligible claim turns can use analysis and a second constrained framing call. Claim facts and summary contents are assembled from approved data. Drafts are checked against the evidence set. The default mock is rules-based. Real adapter transport tests use mocked HTTP.

The largest maintainability cost is the split between graph routing, conversational orchestration, and policy projections. The model adapter exposes an unused free-text generation path in the current chat flow. Several repository protocols have one concrete implementation. Registry and gateway checks provide defense in depth and have coverage. The review did not establish a dependency cycle or a package that can safely be removed. Keep the existing scope and remove unused adapter surface only after checking callers. A slow configured provider can hold SQLite write serialization during a turn.

## Fixtures and security

All six SHA-256 values match the Phase 9 baseline. Seed and repository tests verify policyholder aliases, claim ownership and facts, the representative relationship, financial definitions and document guidance. The consent sequences run in an isolated simulation. Pending, timeout and approval are separate from representative authentication and summary permission. David Chen remains fail-closed without trusted independent proof and delegation. UI prefill uses a synthetic starter message. Displayed case results and gated event data come from the backend.

| Severity | Finding and verification |
| --- | --- |
| Release blocker | Docker CLI unavailable and WSL reports its Linux runtime is absent. No image, network, volume or Compose shutdown assertion could be executed. |
| Release blocker | Configured model is unavailable. Default mock behavior provides zero evidence of real-model conversational quality. |
| Medium, corrected | Direct provider submission returned office-note format guidance. Redaction dropped safe actor vocabulary and retrieval missed the method. Regression reproduced the failure, then passed with controlled actor tokens and item-specific approved guidance. |
| Medium, open | Soft claim-switch wording can reiterate the active case. Unspecific statement-amount queries, misspellings and receipt-to-review wording can trigger generic clarification. Some frustration phrasing repeats the factor prompt. |
| Medium, open | Public deployment would need operator identity, trusted attribution, retention controls and assessment. Current loopback demo uses synthetic records and shared source throttling. Git metadata and Python advisory evidence are unavailable. |
| Low, open | Browser test startup emits Next.js's standalone-output warning. The separate native standalone server test exercised the intended deployment entry point. |

Executed owner-tool, prompt-injection, strict proposal, identity, diagnostics, replay, concurrency, expiry and session-isolation regressions showed no observed authorization bypass. Browser coverage blocked unsolicited origins and verified representative denial. Tests assert durable consent outcomes. Audit events and the workspace originate from backend execution. Review found no evidence in these checks of frontend-owned phase transitions, arbitrary recipients, forged delivery or fabricated timing. This is bounded test evidence.

## Conversation and remediation

The evaluator primary dialogue ran through both branches. Identity progressed from verification through intent to CL-2048. Missing items, replacement options, provider transmission, estimated review time, USD 0.00 recorded payment, USD 1,450 allowed maximum and net fee, and the March 18, 2026 recorded appeal deadline were returned. Completion produced a pending summary. Ambiguity stayed pending. Send and skip completed independently and replay preserved one outcome per session.

Exploratory FastAPI turns included the six example paraphrases, a payment misspelling, refusal and human assistance. The missing-lab-paperwork wording requested document clarification. The statement amount, receipt-to-review prompt and payment misspelling needed clarification. An underspecified switch repeated the active claim. A refusal removed SSN from the requested options, and asking for a human created a simulated handoff. Grounded output was generally precise but repeatedly opened with “I found the claim you’re asking about.” These observations use mock inference.

The correction in `protected_input.py` and `claim_processing.py` keeps a small vocabulary of generic provider and transmission terms and uses fixture guidance for direct provider submission when present. `tests/test_phase4.py` covers two forms. `scripts/smoke_demo.py` now includes missing items, direct provider submission, the financial-field explanation and the full affirmative consent wording. No fixture changed.

## Execution and deployment

| Command or check | Result |
| --- | --- |
| `python -m pytest -q --tb=short` | Baseline 101 passed, 3 live skips. Final 102 passed, 3 live skips, zero failures. |
| `npm run typecheck`, `npm run test`, `npm run test:e2e` from `frontend/` | TypeScript passed, 3 frontend unit and 10 Chromium tests passed. Nine Chromium tests use both services. |
| `python -m evaluation.run --provider mock --output evaluation/reports/phase10_deterministic.json` | 20/20 synthetic scenarios. [Measured output](../evaluation/reports/phase10_deterministic.json). |
| `python -m evaluation.run --provider configured --output evaluation/reports/phase10_real_model_status.json` | `NOT_EXECUTED`. [Status artifact](../evaluation/reports/phase10_real_model_status.json). |
| `python scripts/smoke_demo.py --url http://127.0.0.1:53004` | Native standalone frontend and FastAPI at port 53003. Health and readiness returned 200. Send took 1.21 s and skip took 1.78 s for the full transcripts. Four customers, five claims and two summary outcomes persisted across native backend restart. Servers were stopped after verification. |
| `docker compose version` and `wsl.exe --list --quiet` | Docker command unavailable, WSL runtime absent. Earlier parser and clean dependency evidence remains in the [submission checklist](SUBMISSION_CHECKLIST.md). |

## Internal scorecard

| Category | Score | Evidence and deductions |
| --- | ---: | --- |
| Deterministic SOP | 20/20 | Phase traces and guard matrix in `test_phase4.py` and `test_phase8.py`. |
| Identity and authorization | 14/15 | Foundation, Phase 2 and browser coverage. Representative self-service remains unavailable pending business rules. |
| Real LLM intelligence | 4/15 | Adapter, schema validation and offline transport only. Live quality earns no points. |
| Cross-phase memory | 8/10 | Preserved hints and typed discussion. Partial values are process-local, and underspecified claim switches remain weak. |
| Grounded processing | 9/10 | Fixture-backed primary workflow and Phase 4 tests. Some paraphrases still need clarification. |
| Guardrails and emotional recovery | 7/10 | Phase 5 thresholds and refusal coverage. Empathy is uneven in exploratory mock turns and handoff is simulated. |
| Email and post-processing | 8/8 | Phase 7, Phase 9 and HTTP send/skip/replay evidence for the requested mock flow. |
| Frontend usability | 4/5 | Ten Chromium checks and native gateway smoke. Wider browser and accessibility evaluation remain open. |
| Testing and evaluation | 4/4 | Backend, Chromium and versioned synthetic metrics with explicit live skips. |
| Docker and documentation | 2/3 | Source and parser evidence, setup guide and native smoke. Container runtime remains unverified. |
| **Total** | **80/100** | **NOT_READY for final submission.** |

Before submission, run the fresh-volume checks in [deployment](DEPLOYMENT.md) and execute configured-model evaluation with the primary and exploratory transcripts. After those gates, prioritize better uncertainty handling, concise response framing, browser accessibility coverage and an approved representative-authentication policy.

## Documentation synchronization

| Document | Reviewed | Updated | Changes |
| --- | --- | --- | --- |
| AGENTS.md | Yes | No | Engineering boundaries and commands remain accurate. |
| SPEC.md | Yes | Yes | Document-specific direct submission guidance. |
| PROGRESS.md | Yes | Yes | Phase 10 findings, counts and submission gates. |
| DECISIONS.md | Yes | No | The existing architecture decisions remain accurate. |
| README.md | Yes | Yes | Full synthetic opening and independent status. |
| ARCHITECTURE.md | Yes | No | Service boundaries and diagrams remain accurate. |
| REQUIREMENTS_TRACEABILITY.md | Yes | No | Existing coverage and partial delivery status remain accurate. |
| SECURITY_AUDIT.md | Yes | No | Existing findings remain accurate. Latest regression scope is recorded here. |
| EVALUATION_REPORT.md | Yes | Yes | Phase 10 metrics reference. |
| DEMO_GUIDE.md | Yes | No | Demonstration steps remain accurate. |
| DEPLOYMENT.md | Yes | No | Commands and Docker limitation remain accurate. |
| SUBMISSION_CHECKLIST.md | Yes | Yes | Linked latest review and clarified evidence scope. |
| FINAL_REVIEW.md | Yes | Created | Independent evidence, findings and scorecard. |
