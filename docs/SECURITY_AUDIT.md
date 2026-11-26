# Security Audit

Internal Phase 8 engineering review of the synthetic demo. It covers repository controls and tests and does not certify production security.

Phase 9 reran the security regressions and checked both consent branches and request replay against the real native gateway. The demo manifest binds the frontend to loopback, keeps FastAPI on the Compose bridge, and gives provider credentials only to the backend. Non-root users, read-only root filesystems and dropped capabilities are configured. Their enforcement inside running containers remains unverified.

## Findings and remediation

| Severity | Finding | Affected component | Remediation and retest |
| --- | --- | --- | --- |
| Critical | No critical failure observed in executed authorization, phase, representative, cross-session, and mock-consent checks | Backend and browser | Phase 8 owner-tool matrix, existing isolation/consent checks and evaluation traces passed. This finding is limited to executed cases. |
| Medium | JSON was parsed or forwarded before a transport byte cap | FastAPI and Next.js gateway | Cap streamed JSON at 128 KiB and return 413. Enforce JSON media type with 415. Redacted malformed errors retain 422. Phase 8 exercises oversized streamed input and safe errors. |
| Medium | Malformed provider metadata could escape normalized error handling or pass arbitrary token values to telemetry | `llm.py` | Reject invalid usage structure and normalize token fields to nonnegative integers or absent. Offline provider contract tests passed. |
| Low | Exhausted tool budget still permitted an ownership lookup | `workflow.py` | Move budget evaluation before repository lookup. Regression asserts the check is never invoked after budget exhaustion. |
| Low | Privacy projection dropped processing terms needed for fax guidance | `protected_input.py` | Add approved generic channel terms. Regression drives the paraphrase through FastAPI and asserts approved guidance. |
| High for production | Shared demo source throttle, app-layer credentials, general rate limits, operational PII assurance and operator identity are insufficient for public production exposure | Backend and gateway | Keep loopback demo deployment. Public deployment requires an explicit perimeter, trusted proxy attribution, HTTPS, secret distribution and a production security assessment. The current Compose package publishes only the local frontend. |

## Controls exercised

- Sessions use a generated bearer credential, stored as a hash on the backend and kept in a strict HttpOnly cookie at the browser gateway. Authenticated reads and mutations check session ownership and expiry. Chromium verifies unsolicited origins are denied and JavaScript cannot read the credential cookie.
- Verification, phase and ownership gates protect the 11 claim tools. Rejected requests return safe responses. Representative authority remains fail-closed. The structured model contract forbids client or provider writes to protected state.
- Replay uses a session-bound message ID and content fingerprint. Mock email uses a unique, persisted session outcome and revision-bound explicit consent. Concurrent requests and process restart produced one logical simulated delivery. The external provider acceptance-versus-persistence failure window cannot be tested with the SQLite-only mock.
- Safe message rendering, local PII extraction, redacted context, and approved evidence assembly reject tested overrides and fabricated payment, upload, document, handoff, or email claims. Diagnostic requests require the demo key and bearer and exclude raw identity inputs.
- The npm registry audit completed with zero findings among the audited dependencies. Python `pip check` found no broken requirements. A Python vulnerability scanner was unavailable, so Python CVE scanning and supply-chain certification remain open.

## Residual limitations

Model quality and novel misclassification remain outside the executed offline coverage. No live provider, real email, live representative, production identity proofing, external security assessment, or production compliance evaluation was run. Data retention, authorized representative delegation, recipient policy, and exact appeal cutoff require business approval. See [traceability](REQUIREMENTS_TRACEABILITY.md).
