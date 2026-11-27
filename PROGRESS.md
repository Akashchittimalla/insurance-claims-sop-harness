# Project notes

ClaimAssist is a take-home prototype built from the assessment starter and tested with synthetic data. The hosted mock demo and Docker setup are available for review. The [README](README.md#verification-results) has the latest results, including the separate live Gemini run.

## Prototype limits

- Email and representative handoff are simulated. Representative relationships trigger review and grant no claim access.
- Render Free can sleep, and hosted SQLite session data resets when the service restarts. Local Compose uses a named volume.
- The checks cover the included cases. See the [security notes](docs/SECURITY_AUDIT.md) for what would need more work before real customer use.

[Design decisions](DECISIONS.md) | [Evaluation details](docs/EVALUATION_REPORT.md)
