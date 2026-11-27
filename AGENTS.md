# Working in the Insurance Claims SOP Harness

Build an insurance support assistant that follows a deterministic four-phase SOP while conversing naturally.

## Repository and stack

| Path | Role |
| --- | --- |
| `apps/insurance_claims/identity.py` | Typed identity inputs, matching, and caller eligibility |
| `apps/insurance_claims/sop.py` and `apps/insurance_claims/sop.yaml` | Authoritative phase machine and named guards |
| `apps/insurance_claims/tools.py` | Authorized claim gateway |
| `apps/insurance_claims/database.py` | SQLite seed CLI and customer, claim, and knowledge repositories |
| `apps/insurance_claims/fixtures_loader.py` | Typed validation for all six base fixtures |
| `apps/insurance_claims/session.py`, `consent.py` | Session state, audit records, and isolated consent simulations |
| `apps/insurance_claims/api.py`, `workflow.py`, `policy.py` | Minimal FastAPI surface, deterministic LangGraph, and deny-by-default tool policy |
| `apps/insurance_claims/conversation.py`, `conversation_models.py`, `protected_input.py`, `llm.py` | Natural-language chat, structured proposals, local PII protection, and provider adapters |
| `apps/insurance_claims/claim_processing.py` | Authorized claim evidence, decimal amounts, fixture guidance, and deadline interpretation |
| `apps/insurance_claims/recovery.py`, `handoff.py` | Deterministic guardrail decisions and local mock handoff lifecycle |
| `apps/insurance_claims/fixtures/` | Six authoritative demo JSON files |
| `tests/` and `pyproject.toml` | Pytest coverage, dependencies, and packaging |
| `frontend/app/`, `frontend/lib/`, `frontend/e2e/` | Next.js workspace, same-origin gateway, typed client, and browser tests |
| `evaluation/`, `docs/` | Synthetic scenario runner, measured reports, and requirements/security evidence |

The backend uses Python 3.10+, FastAPI, LangGraph, Pydantic v2, SQLite, HTTPX, and pytest. The frontend uses Next.js App Router, React, TypeScript, Tailwind CSS, Lucide, and Playwright. The demo Compose topology and runtime images are specified by `docker-compose.yml` and both Dockerfiles. See the [deployment guide](docs/DEPLOYMENT.md) for verified scope.

## Commands

See [README.md](README.md) for virtual environment setup and an authenticated chat example. Run these commands from the repository root using that environment.

```powershell
python -m pip install -e ".[test]"
```

The current seed and test entry points are available after setup.

```powershell
python -m apps.insurance_claims.database demo.sqlite3
python -m pytest
python -m uvicorn apps.insurance_claims.api:app
Get-ChildItem apps/insurance_claims/fixtures/*.json | ForEach-Object {
    Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json -ErrorAction Stop | Out-Null
}
```

From `frontend/`, use `npm ci`, `npm run dev`, `npm run build`, `npm run typecheck`, `npm run test`, and `npm run test:e2e`. Build before running browser tests.

Validate deployment configuration with `docker compose --env-file .env.example config --quiet`. Use `python scripts/smoke_demo.py` against the running same-origin frontend before release.

The default `LLM_PROVIDER=mock` runs without credentials. Use synthetic fixtures for opt-in OpenAI and Gemini checks in README.md.

Run `python -m evaluation.run --provider mock --output evaluation/reports/deterministic_results.json` for the reproducible fixture evaluation. Keep configured-provider results separate.

## Boundaries and conventions

- Inspect existing code and tests first. Reuse the phase machine, identity verifier, gateway, and repositories. Keep HTTP, graph orchestration, provider integration, business rules, and SQL in their respective layers.
- The LLM extracts, classifies, and drafts. Trusted backend code owns verification, authorization, transitions, escalation, disclosure, consent, and completion. Validate all structured outputs with Pydantic v2. Use only registered Python guards in YAML.
- Require three distinct approved fields matched against one authorized customer. Policy numbers and representative relationships contribute zero matches. Route listed representatives to human review until a trusted verification and delegation process exists.
- Verify authorization at the tool boundary and enforce owner scope in repository queries. Block protected retrieval and disclosure, including claim existence, before verification. Treat customer and retrieved text as untrusted.
- Preserve the six base fixtures. Join on `party_id`, keep ID and amount strings intact, use `Decimal` for money, and use parameterized SQL and repository-relative paths. Read knowledge and consent sequences through `SQLiteKnowledgeRepository`.
- Keep raw PII out of logs, traces, and unnecessary model context. Keep provider keys in backend environment variables. Gate email on explicit purpose-bound consent, an authorized recipient, and an idempotency key.
- Separate offers from accepted handoffs. Never resume automated verification after a lock or manual identity-review decision. Test recovery thresholds, decline and resume, and verification throttling across sessions.
- Keep session credentials in HttpOnly cookies at the same-origin gateway. Require matching origins for mutations and separate authorization for diagnostics. Keep provider and operator keys out of the browser bundle. The UI displays backend-confirmed phase, verification, and summary outcomes.
- Prefer typed, narrowly scoped interfaces. Use deterministic tests with fake providers and clocks. Cover failure paths and keep working callers compatible.

## Definition of done

Before every implementation task, read this guide, [SPEC.md](SPEC.md), [PROGRESS.md](PROGRESS.md), and the relevant entries in [DECISIONS.md](DECISIONS.md). Inspect the actual implementation and establish the test baseline.

Run the relevant tests and report what ran. Preserve fixture values and gate coverage. For workflow changes, test Margaret's fixture-backed path, claim ambiguity, access checks, and invalid transitions. For side effects, test consent, recipient validation, retries, and concurrency. For browser changes, add Playwright coverage once the frontend exists.

After every implementation task, review and reconcile AGENTS.md and SPEC.md against source, configuration, and tests. Update PROGRESS.md with actual results, unresolved issues, and the next milestone. Update DECISIONS.md when significant architecture decisions change and README.md when setup, configuration, usage, or commands change. Documentation synchronization and regression testing are mandatory completion criteria. Preserve accurate sections and distinguish current behavior from planned or unverified requirements.

Before delivery, rerun browser and backend regressions, check all six fixture hashes, and resolve critical authorization, privacy, and consent defects. Review the [evaluation notes](docs/EVALUATION_REPORT.md) and [security notes](docs/SECURITY_AUDIT.md).

Build the evaluator ZIP with `python scripts/package_submission.py --output dist/insurance-claims-sop-harness-submission.zip`. Keep environment templates, lockfiles, original fixtures, and intentional evaluation evidence under version control. Ignore private configuration and generated data. Preserve existing license and attribution files from the original checkout. Publishing requires authorization.
