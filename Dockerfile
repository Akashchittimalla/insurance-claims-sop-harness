FROM python:3.11-slim-bookworm AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.runtime.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --only-binary=:all: -r requirements.runtime.lock

FROM python:3.11-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system --gid 10001 claims \
    && useradd --system --uid 10001 --gid claims --no-create-home claims \
    && install -d -o claims -g claims -m 0700 /app/data
COPY --from=dependencies /opt/venv /opt/venv
COPY apps/insurance_claims ./apps/insurance_claims
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "apps.insurance_claims.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
