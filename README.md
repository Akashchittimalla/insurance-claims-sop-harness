# Insurance Claims SOP Harness

[Open the hosted demo](https://insurance-claims-sop-harness-demo.onrender.com) ? [Five-minute walkthrough](docs/DEMO_GUIDE.md)

ClaimAssist is a prototype built from the assessment starter and tested with synthetic data. It verifies callers, answers questions about authorized claims, and asks permission before simulating a summary email.

## Try Margaret's claim

1. Start a **New conversation**, click **Load Margaret's claim scenario**, and send the prefilled message. The app verifies three identity fields and resolves Margaret's January healthcare denial to **CL-2048**.
2. Ask **What if I can't obtain the pathology report?** or **How much did insurance pay?** The app gives document guidance and reports **USD 0.00** in recorded payment.
3. Say **That's everything.** Review the denied status, topics discussed, and missing documents. Choose **Send email summary** or **Skip email**. Delivery is simulated.

The hosted gateway reported **Mock provider** in the reviewer check on November 26, 2026. Use synthetic details only. The Render Free service can take about a minute to wake, and its sessions reset on restart. The [split-turn walkthrough](docs/DEMO_GUIDE.md#split-turn-show-the-verification-gate) shows what happens when the caller provides only two fields and a policy number.

## Run locally with Docker

With Docker running, clone the repo and start the default mock demo:

```bash
git clone https://github.com/Akashchittimalla/insurance-claims-sop-harness.git
cd insurance-claims-sop-harness
docker compose up --build --wait
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). A fresh clone uses mock mode without a key. Use `docker compose down` to stop the app and preserve the SQLite volume. See the [deployment guide](docs/DEPLOYMENT.md) for native setup and restart checks.

## Run with your own Gemini API token

Create a local `.env` next to `docker-compose.yml` using [.env.example](.env.example) as a template. In PowerShell, run `if (!(Test-Path .env)) { Copy-Item .env.example .env }` from the repository root. Keep the key in the backend environment and out of Git.

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.1-flash-lite
LLM_API_KEY=your-gemini-api-key
MAX_REASONING_ITERATIONS=1
```

Run `docker compose up -d --wait`. Start a new conversation and send Margaret's opening message. The header should show **Live provider**. To confirm Gemini actually handled a turn, run `docker compose logs --since 2m backend` and look for `model outcome=ok stage=ConversationAnalysis provider=gemini` after that turn. The badge alone shows the configuration.

The OpenAI adapter uses `LLM_PROVIDER=openai`, `LLM_MODEL` set to an OpenAI Chat Completions model that supports JSON output and temperature, and an OpenAI key in `LLM_API_KEY`. The hosted mock deployment does not request a token.

## How it works

The LLM interprets the request and can propose wording. The backend verifies three distinct approved fields, authorizes claim reads, advances SOP phases, and enforces explicit consent. The Gemini profile above uses live turn analysis and deterministic, fixture-backed response rendering. The Next.js UI talks to FastAPI through a same-origin gateway. LangGraph coordinates the workflow and SQLite stores demo records and session state. [Architecture](docs/ARCHITECTURE.md) ? [SOP specification](SPEC.md)

## Verification results

| Area | Recorded evidence | Reviewer check on November 26, 2026 |
| --- | --- | --- |
| Docker | Both images built, both services became healthy, and summary outcomes survived a backend restart. [Docker evidence](docs/EVALUATION_REPORT.md#what-was-exercised-on-november-26-2026) | Rebuilt and started an isolated Compose project. Split-turn verification, both consent paths, scope handoff, and refusal recovery passed through the gateway. |
| Mock evaluation | 20/20 synthetic scenarios passed. [Recorded report](evaluation/reports/phase11_deterministic.json) | 20/20 passed again. The deployed mock gateway also passed the split-turn, both consent, and recovery checks. |
| Live Gemini evaluation | 20/20 passed with Flash-Lite, one model analysis pass per turn, a 6.2-second request interval, one retry and a 15-second timeout. [Full recorded report](evaluation/reports/gemini_live_final_status.json) | Margaret send passed 1/1, with two successful Gemini analysis calls. The full suite result is from the recorded run. |
| OpenAI adapter coverage | HTTP transport and response validation are exercised with a mocked upstream. [Adapter tests](tests/test_phase3.py) ? [Earlier opt-in status](evaluation/reports/phase10_real_model_status.json) | Offline coverage passed in the backend suite. Live OpenAI inference was not exercised. |

Email and human handoff are simulated. Representative access requires human review.

[Demo guide](docs/DEMO_GUIDE.md) | [Evaluation notes](docs/EVALUATION_REPORT.md) | [Security notes](docs/SECURITY_AUDIT.md)
