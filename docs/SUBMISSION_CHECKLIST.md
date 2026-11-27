# Submission checklist

**READY_WITH_LIMITATIONS** for a native synthetic demo, verified on 2026-11-26. Phase 9 stays open because Docker runtime and configured-model evidence are mandatory.

| Acceptance check | Status | Evidence |
| --- | --- | --- |
| Source and architecture inspected | Pass | See [architecture](ARCHITECTURE.md), [phase assessment](../PROGRESS.md), and [traceability](REQUIREMENTS_TRACEABILITY.md). |
| Six original fixtures unchanged | Pass | SHA-256 matched baseline for all six sources. The archive verifier compares fixture bytes with source and checks CRCs. |
| Fresh native dependency installation | Pass | CPython 3.11 exact lock and clean frontend npm lock installation. `pip check` reported no broken requirements. All 47 pinned Linux x86-64 wheels resolved for CPython 3.11. |
| Compose configuration | Pass | Official standalone Compose v5.8.0 validated the manifest with the example environment. Exit 0. |
| Backend and frontend Docker image builds | Blocked | Docker CLI and engine unavailable. WSL Linux runtime unavailable. Image sizes and cold container startup are unmeasured. |
| Compose startup, readiness, SQLite volume ownership and persistence | Blocked | Requires a Docker engine. Run the checks in [deployment](DEPLOYMENT.md). |
| Actual native frontend and backend integration | Pass | Standalone Next.js at `http://127.0.0.1:60120` reached FastAPI at `http://127.0.0.1:60119`. Both addresses were temporary and the test processes have stopped. Frontend, health and readiness returned 200. |
| Native database initialization and restart | Pass | Four customers, five claims and two summary outcomes. All three counts were preserved after restarting FastAPI against the same temporary SQLite file. Readiness returned 200 after restart. |
| Complete Margaret transcript and both consent paths | Pass | HTTP smoke reached CL-2048 after verification, retrieved alternative document guidance and review estimate, returned USD 0.00 and the recorded appeal deadline, and offered the summary. Ambiguous consent remained pending. Explicit send produced `simulated`, skip produced `declined`, and each exact replay left one outcome for its session. |
| Security regressions and isolation | Pass | Test suites covered early and cross-owner access, forged authority, injection, representative review, duplicate and ambiguous consent, cross-origin mutations and independent sessions. See [security audit](SECURITY_AUDIT.md). |
| Real provider, real email and live handoff | Limited | Configured evaluation recorded `NOT_EXECUTED` because provider/model/credential configuration was unavailable. Email and handoff are simulated. |
| Browser screenshots | Pass | [Desktop](screenshots/verified-desktop.png) and [mobile](screenshots/mobile-workspace.png) from Chromium using synthetic fixtures. |
| Git hygiene and publishing | Blocked | Workspace has no Git metadata. The allowlisted archive excludes private dotenv files, dependencies, transient data, and generated build output. No hosted demo URL. |

The [Phase 10 independent review](FINAL_REVIEW.md) classifies final submission as **NOT_READY** and records the latest regression results. This checklist preserves the Phase 9 measurements.

## Recorded checks

| Command | Exit | Result |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m pytest -q --tb=short` | 0 | Baseline 100 passed, 3 skipped. Final 101 passed, 3 skipped, 0 failed. The skips require a configured live provider. |
| `.venv/Scripts/python.exe -m pytest --collect-only -q` | 0 | 104 collected. |
| `python -m pip --isolated install --only-binary=:all: -r requirements.runtime.lock` and `python -m pip check` in a fresh venv | 0 | Native runtime lock installed and imports resolved. |
| `python -m pip --isolated download --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --implementation cp --python-version 3.11 --abi cp311 -r requirements.runtime.lock` | 0 | 47 Linux x86-64 wheels downloaded. This verifies dependency availability for the selected platform. |
| `npm ci --no-audit --no-fund`, `npm run build` in a clean frontend copy | 0 | Dependency install and standalone production build passed. |
| `npm run typecheck`, `npm run test`, `npm run test:e2e` from `frontend/` | 0 | TypeScript passed. Three frontend unit and ten Chromium tests passed. Nine Chromium tests use both running services and one intercepts the API. |
| `docker-compose --env-file .env.example config --quiet` | 0 | Standalone manifest validation. |
| `python scripts/smoke_demo.py --url http://127.0.0.1:60120` | 0 | Both HTTP paths passed. Native startup probes took 5.62 s for FastAPI readiness and 2.60 s for the frontend. Send took 569 ms and skip 368 ms for their full transcripts. Post-restart readiness took 4.52 s. Single-run wall times include polling and are neither container nor provider benchmarks. |
| `python -m evaluation.run --provider mock --output evaluation/reports/phase9_deterministic.json` | 0 | 20/20 scenarios. Chat p50 27.228 ms and p95 41.580 ms across 37 turns. See [evaluation report](EVALUATION_REPORT.md). |
| `python -m evaluation.run --provider configured --output evaluation/reports/phase9_real_model_status.json` | 0 | Status artifact only. No model inference, token or cost sample. |
| `git status --short` | 128 | No Git metadata. |
| `python scripts/package_submission.py` | 0 | Curated source ZIP verified. Local links and archive paths checked. A targeted scan found no files or values matching common credential formats. |

See [deployment](DEPLOYMENT.md) for first-run and stop commands, environment variables, and volume handling. See [SPEC](../SPEC.md) and [progress](../PROGRESS.md) for open business rules, including representative delegation, alternative identity proof, approved recipients, retention and production authentication. A Python advisory scan and broader accessibility and cross-browser validation remain outstanding.

## Docker Desktop verification on 2026-11-26

Compose verification passed in the GitHub checkout using the Linux engine, project `claims-compose-verification`, and loopback port 3011. Both images built with the available cache. Both services became healthy. The full smoke test exited 0 with one simulated send and one decline. After restarting the backend, both services were healthy and SQLite still contained exactly one outcome per disposition. `docker compose down` stopped the test services and preserved the test volume. Earlier entries below and above record the pre-Docker audit. Configured real-model evaluation remains open.

## Step 11 packaging and verification

The 2026-11-26 Gemini follow-up verified live communication with `gemini-3.1-flash-lite` and passed 8 of 20 scenarios, including Margaret send, skip, and ambiguous consent. The cross-owner and representative scenarios failed their expected flow checks and stayed in verification without a claim or tool calls. Backend regression passed with 105 tests and 3 opt-in live skips. Overall live evaluation remains open. [Measured Gemini evaluation](../evaluation/reports/gemini_live_schema_status.json)

The evaluator ZIP is generated with `python scripts/package_submission.py --output dist/insurance-claims-sop-harness-submission.zip`. It includes backend and frontend source, all six fixtures, Docker configuration, dependency manifests and locks, environment templates, tests, evaluation evidence, and documentation with two synthetic screenshots. Exclusions cover private configuration, Git metadata, dependency directories, caches, SQLite data, logs, and transient browser output.

| Command or review | Result |
| --- | --- |
| `python -m pytest -q --tb=short` | Exit 0. 102 passed, 0 failed, 3 real-provider skips. |
| `python -m pip --isolated install --only-binary=:all: -r requirements.runtime.lock`, `python -m pip check` | Exit 0 in a fresh CPython 3.11 environment in the extracted archive. |
| `npm ci --no-audit --no-fund`, `npm run build`, `npm run typecheck`, `npm run test` | Exit 0 from the isolated source extraction. The build produced a standalone server and three frontend unit tests passed. |
| `npm run test:e2e` | Exit 0 in the isolated source extraction. 10 Chromium tests passed. |
| `python scripts/smoke_demo.py --url http://127.0.0.1:58772` | Exit 0 in standalone native mode. Both consent branches passed. Four customers, five claims and two summary outcomes persisted across backend restart. Health, readiness and frontend returned HTTP 200. The temporary services were stopped. |
| Official standalone Compose v5.8.0, `--env-file .env.example config --quiet` | Exit 0. Image builds and runtime checks remain blocked by the unavailable Docker engine. |
| `python -m evaluation.run --provider mock --output evaluation/reports/phase11_deterministic.json` | Exit 0. 20/20 scenarios. [Measured results](../evaluation/reports/phase11_deterministic.json). |
| `python -m evaluation.run --provider configured` | Exit 0 with `NOT_EXECUTED`. No configured live provider, model and credential. |
| `git rev-parse --show-toplevel` | Exit 128. Working tree, branches, index, remotes and history unavailable. Scratch-repository ignore rules passed. |

The targeted credential scan covered intended source, templates, documentation and evaluation files. Matches were empty settings, runtime reads or settings copies. The selected screenshots were captured from the synthetic demo. The scan cannot establish the contents of unavailable Git history. Preserve the original starter license and attribution when preparing an authorized GitHub repository. This workspace contains no standalone project license or attribution file.
