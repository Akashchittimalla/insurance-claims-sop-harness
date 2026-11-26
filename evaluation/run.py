"""Run synthetic conversations against the real FastAPI application in process."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.insurance_claims.api import create_app
from apps.insurance_claims.database import SQLiteDatabase
from apps.insurance_claims.fixtures_loader import load_fixtures
from apps.insurance_claims.settings import Settings


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "datasets" / "insurance_sop_scenarios.jsonl"
CLOCK = datetime(2026, 11, 26, 18, tzinfo=timezone.utc)
DIAGNOSTIC_KEY = "isolated-evaluation"


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"samples": 0}
    tail = ordered[(95 * len(ordered) + 99) // 100 - 1]
    return {"samples": len(ordered), "min_ms": round(ordered[0], 3),
            "p50_ms": round(median(ordered), 3), "p95_ms": round(tail, 3),
            "max_ms": round(ordered[-1], 3)}


class Measurements(logging.Handler):
    def __init__(self):
        super().__init__()
        self.latencies = defaultdict(list)
        self.tokens = Counter()

    def emit(self, record):
        if record.msg.startswith("authorized tool="):
            tool, duration = record.args
            self.latencies[f"tool.{tool}"].append(duration)
        elif record.msg.startswith("model outcome=ok"):
            stage, _, _, duration, prompt, completion, _ = record.args
            self.latencies[f"model.{stage}"].append(duration)
            if isinstance(prompt, int) and isinstance(completion, int):
                self.tokens.update(input=prompt, output=completion, samples=1)
        elif record.msg.startswith("approved knowledge="):
            topic, duration = record.args
            self.latencies[f"knowledge.{topic}"].append(duration)


def execute(client, scenario, trade, phrases):
    def call(label, action, path, **kwargs):
        start = perf_counter()
        response = getattr(client, action)(path, **kwargs)
        trade.latencies[label].append((perf_counter() - start) * 1000)
        return response

    session = call("api.session", "post", "/api/v1/sessions").json()
    path = "/api/v1/sessions/" + session["session_id"]
    headers = {"Authorization": "Bearer " + session["credential"]}
    trace = []
    metrics = []
    checks = []
    failures = []
    if session["phase"] != "VERIFY_ID":
        failures.append({"step": 0, "checks": ["initial_phase"]})
    for index, step in enumerate(scenario["steps"], 1):
        if "choice" in step:
            view = call("api.summary_preview", "get", path + "/workspace", headers=headers)
            summary = view.json().get("summary")
            if not summary:
                failures.append({"step": index, "checks": ["summary_missing"]})
                metrics.extend((name, False) for name in step["metrics"])
                break
            response = call("api.summary_choice", "post", path + "/summary", headers=headers, json={
                "choice": step["choice"], "revision": summary["revision"],
            })
        else:
            message = phrases.get(step["message"], step["message"])
            label = "api.verification_turn" if step["message"] in phrases else "api.chat_turn"
            response = call(label, "post", path + "/messages", headers=headers,
                            json={"message_id": str(index), "message": message})
        if response.status_code != 200:
            failures.append({"step": index, "checks": ["http_" + str(response.status_code)]})
            metrics.extend((name, False) for name in step["metrics"])
            break
        reply = response.json().get("response", "")
        workspace = call("api.workspace", "get", path + "/workspace", headers=headers).json()
        diagnostic = call("api.events", "get", path + "/events", headers={
            **headers, "X-Demo-Key": DIAGNOSTIC_KEY,
        }).json()
        deliveries = sum(event["event_type"] == "email_delivery_simulated" for event in diagnostic["events"])
        claim = (workspace["claim"] or (workspace["summary"] or {}).get("claim") or {}).get("case_id")
        actual = {"phase": workspace["phase"], "status": workspace["status"], "claim": claim,
                  "disposition": (workspace["summary"] or {}).get("disposition"),
                  "deliveries": deliveries, "intent": diagnostic["intent"],
                  "hint_month": diagnostic["hints"].get("month")}
        failed = [key for key, value in actual.items() if key in step and step[key] != value]
        if step.get("no_claim") and claim:
            failed.append("protected_claim")
        if any(value not in reply for value in step.get("includes", [])):
            failed.append("required_evidence")
        if any(value in reply for value in step.get("excludes", [])):
            failed.append("forbidden_evidence")
        if "identity" in step["metrics"] and step.get("phase") in {"RESOLVE_INTENT", "PROCESS_CASE"}:
            if workspace["verification"] != "verified" or diagnostic["matched"] != 3:
                failed.append("identity")
        if failed:
            failures.append({"step": index, "checks": failed})
        checks.append({"step": index, "metrics": step["metrics"], "passed": not failed})
        metrics.extend((name, not failed) for name in step["metrics"])
        trace.append({"step": index, "phase": actual["phase"], "status": actual["status"],
                      "claim": claim, "delivery": actual["disposition"],
                      "tool_calls_so_far": sum(e["event_type"] == "tool_execution" and e["decision"] == "allowed"
                                               for e in diagnostic["events"]),
                      "transitions": [event["action"] for event in diagnostic["events"]
                                      if event["event_type"] == "phase_transition" and event["decision"] == "allowed"],
                      "simulated_deliveries": deliveries})
    return {"id": scenario["id"], "category": scenario["category"], "passed": not failures,
            "failures": failures, "checks": checks, "trace": trace}, metrics


def evaluate(args):
    raw = DATASET.read_bytes()
    scenarios = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    scenarios = [case for case in scenarios if (not args.category or args.category == case["category"])
                 and (not args.scenario or args.scenario == case["id"])]
    if not scenarios:
        raise SystemExit("No matching scenarios")
    settings = Settings() if args.provider == "configured" else Settings(_env_file=None, llm_provider="mock")
    result = {"mode": args.provider, "dataset": "insurance-sop-v1", "dataset_sha256": hashlib.sha256(raw).hexdigest(),
              "executed_at_utc": datetime.now(timezone.utc).isoformat(), "scenario_clock": CLOCK.isoformat()}
    if args.provider == "configured" and (
        settings.llm_provider == "mock" or not settings.llm_api_key.get_secret_value() or not settings.llm_model
    ):
        return result | {"status": "NOT_EXECUTED", "reason": "A configured real provider, model and credential are required"}
    policyholder = next(row for row in load_fixtures().policyholders if row.party_id == "P9")
    identity = (f"I'm the policyholder. My name is {policyholder.name}, policy {policyholder.policy_number}. "
                f"DOB is {policyholder.dob.isoformat()}, SSN last four is {policyholder.id_last4}.")
    phrases = {"@identity": identity, "@opening": identity + " I'm calling about my denied healthcare claim from January."}
    result["provider"] = settings.llm_provider
    result["model"] = settings.llm_model or "deterministic"
    result["configuration"] = {"extraction_temperature": settings.llm_extraction_temperature,
                               "response_temperature": settings.llm_response_temperature,
                               "tool_budget": settings.max_tool_calls_per_turn}
    measurements = Measurements()
    loggers = [logging.getLogger(f"apps.insurance_claims.{name}")
               for name in ("workflow", "conversation", "claim_processing")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(measurements)
        logger.setLevel(logging.INFO)
    outcomes = []
    totals = defaultdict(Counter)
    database_statements = Counter()
    original_connect = SQLiteDatabase.connect

    def record_statement(statement):
        operation = statement.lstrip().split(None, 1)
        if operation:
            word = operation[0].upper()
            database_statements[word if word in {
                "SELECT", "INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "ROLLBACK", "CREATE",
            } else "OTHER"] += 1

    def instrumented_connect(database):
        connection = original_connect(database)
        connection.set_trace_callback(record_statement)
        return connection
    try:
        with TemporaryDirectory() as directory, patch.object(SQLiteDatabase, "connect", instrumented_connect):
            config = settings.model_copy(update={
                "database_url": f"sqlite:///{Path(directory, 'evaluation.db')}",
                "demo_mode": True, "email_mode": "mock",
                "verification_window_attempts": max(100, 5 * len(scenarios)),
                "demo_diagnostics_key": SecretStr(DIAGNOSTIC_KEY),
            })
            with TestClient(create_app(config, clock=lambda: CLOCK)) as client:
                for case in scenarios:
                    outcome, metrics = execute(client, case, measurements, phrases)
                    outcomes.append(outcome)
                    for name, passed in metrics:
                        totals[name].update({"samples": 1, "passed": int(passed)})
    finally:
        for logger, level in zip(loggers, levels):
            logger.removeHandler(measurements)
            logger.setLevel(level)
    return result | {
        "status": "COMPLETE", "scenarios": len(outcomes), "passed": sum(row["passed"] for row in outcomes),
        "failed_ids": [row["id"] for row in outcomes if not row["passed"]],
        "metrics": {name: {**count, "percentage": round(100 * count["passed"] / count["samples"], 2),
                           "failed_ids": sorted({
                               row["id"] for row in outcomes if any(
                                   name in check["metrics"] and not check["passed"] for check in row["checks"]
                               )
                           })} for name, count in sorted(totals.items())},
        "latencies": {name: distribution(values) for name, values in sorted(measurements.latencies.items())},
        "token_usage": dict(measurements.tokens) or {"samples": 0},
        "database_statement_counts": dict(sorted(database_statements.items())),
        "results": outcomes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("mock", "configured"), default="mock")
    parser.add_argument("--category")
    parser.add_argument("--scenario")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))
    return int(bool(result.get("failed_ids")))


if __name__ == "__main__":
    raise SystemExit(main())
