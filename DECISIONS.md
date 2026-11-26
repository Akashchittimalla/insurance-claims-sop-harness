# Architecture Decisions

These entries are retrospective assessments of the current code. Rationale and alternatives describe trade-offs visible during this audit.

## ADR-001 SOP authority stays on the backend

**Status.** Implemented. See `apps/insurance_claims/sop.py`, `policy.py`, and `workflow.py`.

**Decision.** Use LangGraph to orchestrate turns and named YAML guards to constrain transitions. The verifier, policy, and owner-scoped repository authorize protected access. Providers return validated proposals.

**Rationale and alternatives.** A prompt-only implementation is simpler but cannot enforce identity and ownership. Named Python predicates retain configurable phase gates without executing expressions supplied in YAML.

**Consequences.** A provider change leaves policy independent. A new trusted action requires explicit registration, a typed contract, and authorization tests.

## ADR-002 Use structured SQLite evidence and approved knowledge

**Status.** Implemented. See `apps/insurance_claims/database.py`, `tools.py`, and `claim_processing.py`.

**Decision.** Resolve and recheck claims under the authorized party. Select knowledge from the seeded structured fixture and render critical facts from typed evidence. Allow the model to select approved wording, with a deterministic fallback. Track discussion and pending questions per active case.

**Rationale and alternatives.** Vector retrieval adds infrastructure for a small, keyed dataset. Unrestricted drafting with citations can still introduce fabricated facts. Exact evidence rendering makes monetary values, deadlines, and document requirements testable.

**Consequences.** Subtle paraphrases are less flexible than unrestricted generation. New guidance topics need controlled routing and tests. Switching cases isolates evidence and discussion from the previous case.

Store monetary values as decimal strings and convert to Decimal for authoritative amounts. Binary floating-point arithmetic could change cent precision. Missing money remains distinct from zero, and a recorded value alone cannot establish patient liability.

## ADR-003 Separate replay, consent, and inquiry completion

**Status.** Replay, inquiry completion and simulated consent are implemented. Delivery is planned. See `apps/insurance_claims/session.py`, `consent.py`, and `workflow.py`.

**Decision.** Store session-scoped message replays transactionally. Keep fixture consent simulations purpose-bound. Allow verified inquiry completion through the SOP when required questions are resolved.

**Rationale and alternatives.** Process-local deduplication loses replay state after restart. Reusing a simulated approval for another purpose would authorize an unrelated action. Treating completion as claim adjudication would change business outcomes without authority.

**Consequences.** Repeated messages replay the stored result and SQLite writes serialize in the demo. Claim records remain unchanged by completion. Future delivery needs its own explicit consent, recipient, outcome, and durable idempotency controls.

## ADR-004 Interpret deadlines as business-local dates

**Status.** Implemented. Exact cutoff and eligibility policy remain open. See `apps/insurance_claims/settings.py` and `claim_processing.py`.

**Decision.** Compare the recorded date with an injectable clock in `BUSINESS_TIMEZONE`. Use Chicago as the demo default.

**Rationale and alternatives.** A host-local or UTC date can differ from the business date near midnight. The fixture supplies a date and does not establish an exact cutoff time.

**Consequences.** Due-today wording is date-only. The system does not infer appeal eligibility, extensions, or a time of day. Windows uses the IANA `tzdata` dependency.

## ADR-005 Use one bounded workflow and a provider interface

**Status.** Implemented with mock coverage and offline OpenAI transport verification. Live behavior is unverified.

**Context and decision.** One LangGraph workflow consumes typed candidates from `conversation.py`. `llm.py` contains the provider interface, mock and OpenAI adapters. `session.py` holds structured identity, hint, discussion and consent state.

**Alternatives and rationale.** Separate agents would add coordination for decisions the SOP already owns. A provider SDK embedded in policy would couple authorization to transport. Vector memory can aid retrieval but cannot provide exact authorization state. The implemented approach keeps authority typed and testable.

**Trade-offs and consequences.** Typed routing limits free-form action planning. SQLite provides demo transactions but serializes work during long provider calls. Distributed concurrency and live provider evaluation remain open.

## ADR-006 Keep identity evidence local and fail closed for representatives

**Status.** Demo controls implemented. Alternate ID and representative authorization policy remain open.

**Context and decision.** In `protected_input.py` and `identity.py`, compare normalized aliases within their original field, count distinct approved factors, and keep partial raw candidates process-local. The configured factor threshold cannot fall below three. Representative records establish a relationship for human review. National ID last four stays outside the approved factors.

**Alternatives and rationale.** Providing raw transcripts to the model offers flexibility at a privacy cost. Counting aliases separately overstates evidence, and a family relationship alone cannot establish authority.

**Trade-offs and consequences.** Redaction can lose detail and restarts lose partial candidates. Audit excludes raw verification values. Identity-review handoffs require manual review before protected access can resume. Future delegation requires verified identity, approved scope, purpose and expiry.

## ADR-007 Separate recovery offers from simulated handoff requests

**Status.** Implemented for the demo. See `recovery.py`, `handoff.py`, `conversation.py`, and `workflow.py`.

**Decision and rationale.** Thresholds create offers without ending the workflow. Explicit acceptance creates a persisted mock request. Lockout and identity review fail closed to manual review. Simulated queue and cancellation use trusted saved state. Automatic transfer on emotion or scope alone would interrupt customers who can continue.

**Consequences.** Eligible sessions can cancel and resume the same phase. The mock can report requested, queued, failed or cancelled outcomes. Live dispatch and connected status require an adapter.

## ADR-008 Throttle complete verification attempts across chat sessions

**Status.** Implemented for the demo. See `session.py`, `workflow.py`, and `api.py`.

**Decision and rationale.** Reserve attempts in a SQLite fixed window keyed by an HMAC of the client source. Per-session lockout alone can be evaded by opening another session. A persisted keyed fingerprint avoids retaining the raw source in the throttle table.

**Consequences.** Clients sharing a source also share a limit. Different sources or independent databases require stronger production controls. Trusted proxy configuration is required for reliable source attribution behind a proxy.

## ADR-009 Frontend gateway and authorized execution dashboard

**Decision.** Use Next.js App Router for the workspace and an allowlisted same-origin gateway. Keep bearer credentials in strict HttpOnly cookies. Bind a separate diagnostics proof to the session and require the backend demo key and bearer on each diagnostic request. Update bounded diagnostics after completed actions.

**Rationale and trade-offs.** Direct browser bearer storage or CORS adds credential exposure and configuration burden. Action-triggered reads fit the demo event volume without subscriptions. The gateway centralizes browser security but shares the backend's source throttle for proxied calls.

**Verification.** Use runtime contract tests for the TypeScript client and browser tests against actual FastAPI and Next.js servers with deterministic mock providers.

## ADR-010 Versioned summary choice and simulated delivery

**Decision.** Provide the frontend with a server-generated preview and version. Bind the first explicit send or skip to the current authorized session and store it in one SQLite transaction. Use the registered masked recipient for display and no external transport.

**Rationale and trade-offs.** Browser-generated summaries and frontend consent flags cannot establish trusted facts. An atomic one-outcome record supports safe replay and prevents duplicate mock delivery. Real delivery needs a separate outbox and provider reconciliation. Existing consent fixtures retain their unrelated simulation purpose.

## ADR-011 Verify deterministic gates independently from provider quality

**Decision.** Evaluate the real application with ephemeral SQLite and a versioned synthetic dataset. Use deterministic assertions for authority, amounts, dates and side effects. Exercise concurrency by counting durable outcomes across races and restart. Use Chromium for session isolation and safe browser behavior. Keep configured model results separate from mock results.

**Rationale and trade-offs.** A model judge cannot establish ownership or confirm a side effect. Offline fixtures make comparisons reproducible, with limited conversational variation. Live quality, naturalness and endpoint latency need configured evaluation and human review. Benchmarking records safe stage timings and SQL operation counts rather than request payloads or SQL text.

**Release gate.** A reproduced critical disclosure, authority bypass or unauthorized side effect blocks delivery. Byte bounds apply before parsing, and the tool budget applies before database authorization lookups. See the [security audit](docs/SECURITY_AUDIT.md).

## ADR-012 Package a local two-service demo

**Decision.** Build separate non-root runtime images with Python 3.11 and Node.js 24, bind the frontend to loopback, keep FastAPI on the Compose network, and store SQLite in a named volume. Use the standalone Next.js server, its npm lock, and an exact Python runtime lock. The provider key stays in backend runtime configuration.

**Rationale and alternatives.** A combined image would couple two processes and their health checks. A public backend port would bypass the browser gateway boundary. An external database would add an operational dependency to the synthetic demo. The named volume gives the demo durable state and requires a writable mount owned by the backend runtime UID.

**Consequences.** Local operation requires a Docker engine with Linux containers or the documented native setup. Dependency pins require deliberate refresh and compatibility checks. The single-node SQLite demo and shared proxy-source budget remain production limitations. The standalone Compose parser validated the manifest. Runtime acceptance is open.

## ADR-013 Curate the evaluator package

**Decision.** Ship an allowlisted source archive with the original fixtures, runtime locks, tests, sanitized evaluation evidence, and two selected screenshots. Use Git ignore rules for local state. Keep the existing dependency pins and use the documented local test commands as the verification entry points.

**Rationale and consequences.** Copying the working directory wholesale would include dependency trees, caches, and local configuration. The source manifest makes review and clean setup repeatable. Git tracking, history, and starter attribution must be checked in the original checkout before publishing because this copy has no Git metadata. No new license was assigned.
