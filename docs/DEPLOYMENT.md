# Deployment

## Compose demo

Use a working Docker engine with Linux containers and Docker Compose 2.24 or newer. The backend image uses Python 3.11 and the exact runtime lock. The frontend image uses Node.js 24 and the npm lock. Run from the repository root. The optional dotenv file is local and untracked.

```powershell
Copy-Item .env.example .env
docker compose --env-file .env.example config --quiet
docker compose build
docker compose up -d --wait
docker compose ps
docker compose exec -T backend python -c "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8000/health').read().decode()); print(urlopen('http://127.0.0.1:8000/ready').read().decode())"
python scripts/smoke_demo.py --url http://127.0.0.1:3000
docker compose restart backend
docker compose up -d --wait
docker compose exec -T backend python -c "import sqlite3; c=sqlite3.connect('/app/data/insurance.db'); print(c.execute('SELECT disposition, COUNT(*) FROM summary_outcomes GROUP BY disposition').fetchall())"
docker compose logs --tail 50
docker compose down
```

For Bash use `cp .env.example .env` in place of `Copy-Item`. Preserve an existing private configuration when repeating setup. The SQLite volume survives `docker compose down`. On an empty demo volume the smoke run should add one simulated and one declined outcome. Compare counts before and after restarting. To remove the demo database deliberately, use `docker compose down --volumes`, which deletes stored sessions and outcomes.

| Variable | Scope and default |
| --- | --- |
| `FRONTEND_PORT` | Optional host loopback port, defaults to 3000. |
| `DATABASE_URL` | Compose uses `sqlite:////app/data/insurance.db`. Native development defaults to `sqlite:///./data/insurance.db`. |
| `DEMO_MODE`, `EMAIL_MODE` | Compose enables synthetic seed data and defaults to mock email. |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | Backend-only provider configuration. `mock` works with an empty model and key. |
| `DEMO_DIAGNOSTICS_KEY` | Optional private key shared by the two servers. Empty disables diagnostic access. |
| `BACKEND_API_URL` | Server-only frontend setting. Compose sets `http://backend:8000`. Native default is `http://127.0.0.1:8000`. |
| `BUSINESS_TIMEZONE` | Backend setting, defaults to `America/Chicago`. |

Use `config --quiet` with credentials configured to avoid printing expanded values. The frontend health check probes its HTTP entry point and the backend probes SQLite readiness. Inspect `ps` for an unhealthy service. Check port conflicts, seed errors, and writable volume ownership using the logs. Keep this demo on loopback. Public hosting requires operator authentication, TLS, trusted client attribution, reviewed data handling and secret distribution.

On 2026-11-26, Docker Desktop?s Linux engine validated the manifest, built both images using the available build cache, and started both services on a fresh named volume. The full mock HTTP smoke test passed both consent branches and verified the two persisted outcomes after backend restart. See the [submission checklist](SUBMISSION_CHECKLIST.md).

## Native fallback

Use [README](../README.md) for PowerShell. On Bash install the backend with `python3 -m venv .venv` and `.venv/bin/python -m pip install -e '.[test]'`. Run `.venv/bin/python -m uvicorn apps.insurance_claims.api:app --no-proxy-headers` and start the frontend with `npm ci && npm run dev` from `frontend/`. Run the smoke command above from the repository root.

## Hosted synthetic demo on Render

Create a Render Blueprint from `render.yaml`, which selects a **Free** Docker Web Service. The equivalent manual settings are the repository root as the build context, `./Dockerfile.hosted` as the Dockerfile path, and `/` as the health check path. Render supplies the frontend port and HTTPS URL. FastAPI listens on container loopback. The hosted launcher uses synthetic fixtures, mock email, mock model responses, and disabled developer diagnostics. Use only synthetic inputs. Keep live-model evaluation on the local backend.

The free instance can sleep after inactivity. SQLite sessions are temporary and reset when the instance stops or redeploys. A cold start can take about a minute. The [Render free plan documentation](https://render.com/docs/free) lists the account limits.

Verify an active deployment with `python scripts/smoke_demo.py --url https://YOUR-SERVICE.onrender.com`. Share the URL only after both consent paths pass.
