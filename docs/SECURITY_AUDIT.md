# Prototype security notes

The demo is for synthetic data. These notes describe the implemented controls and the tests that exercised them.

- **Identity and claim access.** The backend counts three distinct approved fields against the same record, checks ownership in the repository, and refuses representative access pending human review. The model and frontend cannot set verification or workflow state.
- **Browser requests.** The gateway keeps the session credential in an HttpOnly cookie and checks the origin on writes. Diagnostics require both the session and a separate key. Render disables diagnostics.
- **Consent and replay.** Explicit send or skip is tied to a summary revision. The masked recipient is taken from the registered address. SQLite replay and concurrency checks observed one simulated outcome per session. Real delivery and provider reconciliation are outside scope.
- **Input and provider responses.** The API and gateway cap JSON request bodies at 128 KiB and reject invalid media types. Provider schemas reject extra authority fields, and malformed usage is excluded from telemetry. The tool budget is checked before owner lookup. Fixture-based tests check redaction and attempted instruction overrides.

The demo uses a shared source-based verification throttle and single-node SQLite. Production use would need reviewed identity and delegation policies, trusted client attribution, operator authentication, retention policy, and a security assessment. Exact appeal cutoff and recipient policies still need business input. [Verification details](EVALUATION_REPORT.md) | [SOP specification](../SPEC.md)
