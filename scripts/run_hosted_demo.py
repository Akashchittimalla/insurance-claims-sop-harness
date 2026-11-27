"""Start the synthetic backend and the public Next.js gateway in one container."""

import os
import signal
from subprocess import Popen, TimeoutExpired
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen


def stop(_signum, _frame):
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    backend_port = 8000
    frontend_port = int(os.environ.get("PORT", "10000"))
    if frontend_port == backend_port:
        backend_port = 8001
    backend_url = f"http://127.0.0.1:{backend_port}"
    env = os.environ | {
        "DATABASE_URL": "sqlite:////app/data/insurance.db",
        "DEMO_MODE": "true",
        "EMAIL_MODE": "mock",
        "LLM_PROVIDER": "mock",
        "LLM_API_KEY": "",
        "DEMO_DIAGNOSTICS_KEY": "",
    }
    services = []
    try:
        backend = Popen(
            ["python", "-m", "uvicorn", "apps.insurance_claims.api:app", "--host", "127.0.0.1",
             "--port", str(backend_port), "--no-proxy-headers", "--no-access-log"],
            env=env,
        )
        services.append(backend)
        deadline = monotonic() + 30
        while backend.poll() is None and monotonic() < deadline:
            try:
                with urlopen(backend_url + "/ready", timeout=1):
                    break
            except (URLError, TimeoutError):
                sleep(0.25)
        else:
            raise SystemExit("Hosted demo backend did not become ready.")

        services.append(Popen(
            ["node", "server.js"], cwd="/app/web",
            env=env | {"HOSTNAME": "0.0.0.0", "PORT": str(frontend_port), "BACKEND_API_URL": backend_url},
        ))
        while all(service.poll() is None for service in services):
            sleep(0.25)
        raise SystemExit("A hosted demo service exited.")
    finally:
        for service in services:
            if service.poll() is None:
                service.terminate()
        for service in services:
            try:
                service.wait(timeout=3)
            except TimeoutExpired:
                service.kill()
                service.wait()


if __name__ == "__main__":
    main()
