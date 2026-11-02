#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in progressive load against an explicitly disposable native CMS contest.

No database access, shell execution, worker bypass, or automatic request retries.
Supply external target/credential/plan JSON. --validate-only performs no network I/O.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import threading
import time
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import requests

REPO = Path(__file__).resolve().parents[2]
NAMES = {"login_burst", "context_read", "autosave", "telemetry", "custom_runs", "official_submissions", "final_minutes"}
PROTECTED = {"taskId", "principalId", "participantIndex", "iteration"}
VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]{0,63})\}\}")
MAX_BODY = 9_000_000


class Invalid(ValueError):
    pass


class Failed(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def bounded(value, low, high, label, integer=False):
    require(type(value) is int if integer else type(value) in (int, float), "Invalid " + label)
    require(math.isfinite(value) and low <= value <= high, "Out-of-range " + label)
    return value


def external(path, private=False):
    path = Path(path).expanduser().resolve(strict=True)
    require(not path.is_relative_to(REPO), "Inputs with credentials/source fixtures must be outside the repository")
    require(path.is_file(), "Input must be a regular file")
    require(path.stat().st_size <= MAX_BODY, "Input JSON exceeds byte limit")
    if private:
        require(not stat.S_IMODE(path.stat().st_mode) & 0o077, "Credential file must have mode0600 or0400")
    return path


def read_json(path, private=False):
    return json.loads(external(path, private).read_text(encoding="utf-8"))


def local_path(value):
    require(isinstance(value, str) and value.startswith("/") and not value.startswith("//"), "Require an origin-relative path")
    parsed = urlsplit(value)
    require(not parsed.scheme and not parsed.netloc and not parsed.fragment and not re.search(r"[\x00-\x20\\]", value), "Invalid request path")
    require(not re.search(r"%(?:2e|2f|5c|00)", value, re.I) and all(part not in (".", "..") for part in parsed.path.split("/")), "Traversal path rejected")
    return value


def category(method, path):
    """Exact native route families only; never arbitrary URL/RPC/admin proxy."""
    method = method.upper()
    path = urlsplit(local_path(path)).path
    ident = r"(?:[A-Za-z0-9_.-]+|\{\{[A-Za-z][A-Za-z0-9_]*\}\})"
    runtime = r"/ide/api/runtime/v1/"
    if method == "GET" and path == "/ide/api/context":
        return "context"
    if method == "POST" and path == "/ide/api/submissions":
        return "official"
    if method == "GET" and re.fullmatch(r"/ide/api/submissions(?:/(?:status/)?" + ident + r")?", path):
        return "feedback"
    if method == "POST" and path == "/ide/api/runtime/v1/executions":
        return "custom"
    if method == "GET" and path == "/ide/api/runtime/v1/execution-capacity":
        return "execution_read"
    if method in ("GET", "POST") and re.fullmatch(runtime + r"executions/" + ident + r"(?:/(?:events|cancel))?", path):
        return "execution_read"
    if method in ("GET", "POST") and re.fullmatch(runtime + r"telemetry/(?:policy|sessions|batches)(?:/" + ident + r"(?:/(?:close|status|events|checkpoints|chunks))?)?", path):
        return "telemetry"
    if method in ("GET", "POST", "PATCH", "DELETE") and re.fullmatch(runtime + r"(?:session|workspaces(?:/" + ident + r"(?:/(?:files|settings|snapshots|executions|execution-resources))?)?|sync/batches|sync/status/" + ident + r")", path):
        return "workspace"
    raise Invalid("Request route is outside the load harness allowlist")


def validate_request(step):
    require(isinstance(step, dict) and set(step) <= {"method", "path", "json", "expect", "assert", "capture", "newIds"}, "Invalid request fixture fields")
    require(step.get("method") in ("GET", "POST", "PATCH", "DELETE"), "Invalid request method")
    kind = category(step["method"], step.get("path", ""))
    require(isinstance(step.get("expect", [200]), list) and 1 <= len(step.get("expect", [200])) <= 10, "Invalid expected statuses")
    for value in step.get("expect", [200]):
        bounded(value, 100, 599, "HTTP status", True)
    require(isinstance(step.get("assert", {}), dict) and isinstance(step.get("capture", {}), dict), "Invalid response contract")
    for key, value in step.get("capture", {}).items():
        require(VARIABLE.fullmatch(key) and key not in PROTECTED and isinstance(value, str), "Invalid captured variable")
    require(isinstance(step.get("newIds", []), list) and len(step.get("newIds", [])) <= 100, "Invalid generated IDs")
    for name in step.get("newIds", []):
        require(isinstance(name, str) and VARIABLE.fullmatch(name) and name not in PROTECTED, "Invalid generated ID")
    require(len(json.dumps(step, ensure_ascii=True).encode()) <= MAX_BODY, "Fixture request too large")
    return kind


def validate(target, credentials, plan, options):
    require(isinstance(target, dict) and target.get("schemaVersion") == 1 and target.get("disposable") is True, "Target must explicitly declare schemaVersion1 and disposable:true")
    require(str(UUID(target["targetId"])) == target["targetId"], "Target id must be canonical UUID")
    require(options.confirm_disposable == target["targetId"], "--confirm-disposable must match targetId")
    parsed = urlsplit(target.get("origin", ""))
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and parsed.path in ("", "/") and not parsed.query and not parsed.fragment, "Target must be a bare HTTPS origin")
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    require(local or options.allow_remote_disposable, "Non-loopback targets require --allow-remote-disposable")
    require(str(UUID(target["installationId"])) == target["installationId"], "Expected installation UUID is required")
    bounded(target["contestId"], 1, 2**53-1, "contestId", True)
    require(isinstance(target.get("contestName"), str) and (target["contestName"].startswith("ide-load-") or target["contestName"] == "ide-smoke"), "Disposable contest name must start ide-load- or equal ide-smoke")
    base = target.get("cwsBasePath", "/")
    require(local_path(base) == base and "?" not in base and base.endswith("/"), "cwsBasePath must end in slash")
    if target.get("caBundle"):
        require(Path(target["caBundle"]).is_file(), "TLS CA bundle not found")
    require(isinstance(credentials, list) and 1 <= len(credentials) <= 350, "Supply1..350 distinct disposable participants")
    usernames = set()
    for entry in credentials:
        require(isinstance(entry, dict) and set(entry) <= {"username", "password", "taskId", "variables"}, "Invalid credential fields")
        require(isinstance(entry.get("username"), str) and entry["username"] and entry["username"] not in usernames, "Credentials must have distinct usernames")
        require(isinstance(entry.get("password"), str) and entry["password"], "Password required")
        bounded(entry["taskId"], 1, 2**53-1, "taskId", True)
        require(isinstance(entry.get("variables", {}), dict) and all(VARIABLE.fullmatch(k) and k not in PROTECTED for k in entry.get("variables", {})), "Invalid fixture variables")
        usernames.add(entry["username"])
    require(isinstance(plan, dict) and plan.get("schemaVersion") == 1 and isinstance(plan.get("scenarios"), list) and 1 <= len(plan["scenarios"]) <= 30, "Invalid plan")
    total_requests, total_seconds = 0, 0
    for scenario in plan["scenarios"]:
        require(isinstance(scenario, dict) and set(scenario) <= {"name", "participants", "iterations", "concurrency", "ratePerSecond", "rampSeconds", "durationSeconds", "timeoutSeconds", "requestsFile"}, "Invalid scenario fields")
        require(scenario.get("name") in NAMES, "Unknown scenario")
        count = bounded(scenario["participants"], 1, min(350, len(credentials)), "participants", True)
        bounded(scenario["concurrency"], 1, count, "concurrency", True)
        iterations = bounded(scenario["iterations"], 1, 10000, "iterations", True)
        bounded(scenario["ratePerSecond"], 0.01, 1000, "ratePerSecond")
        duration = bounded(scenario["durationSeconds"], 1, 3600, "durationSeconds")
        bounded(scenario["rampSeconds"], 0, min(600, duration), "rampSeconds")
        bounded(scenario.get("timeoutSeconds", 10), 0.1, 30, "timeoutSeconds")
        total_seconds += duration
        if scenario["name"] in ("login_burst", "context_read"):
            require(not scenario.get("requestsFile"), "Built-in scenarios do not take fixture requests")
            scenario["fixture"] = {"steps": [], "setup": []}
            total_requests += count * (3 * iterations + 3)
            continue
        fixture = read_json(scenario.get("requestsFile", ""))
        require(isinstance(fixture, dict) and set(fixture) <= {"schemaVersion", "actorIds", "setup", "steps"} and fixture.get("schemaVersion") == 1, "Invalid fixture")
        require(isinstance(fixture.get("steps"), list) and 1 <= len(fixture["steps"]) <= 100 and isinstance(fixture.get("setup", []), list) and len(fixture.get("setup", [])) <= 100, "Fixture needs bounded steps/setup")
        require(isinstance(fixture.get("actorIds", []), list) and len(fixture.get("actorIds", [])) <= 100, "Invalid actor IDs")
        for name in fixture.get("actorIds", []):
            require(isinstance(name, str) and VARIABLE.fullmatch(name) and name not in PROTECTED, "Invalid actor ID name")
        kinds = {validate_request(step) for step in fixture.get("setup", []) + fixture["steps"]}
        expected = {"autosave": {"workspace"}, "telemetry": {"workspace", "telemetry"}, "custom_runs": {"workspace", "custom", "execution_read"}, "official_submissions": {"workspace", "official", "feedback"}, "final_minutes": {"workspace", "telemetry", "custom", "execution_read", "official", "feedback", "context"}}[scenario["name"]]
        require(kinds <= expected, "Fixture routes do not match scenario category")
        require("official" not in kinds or options.allow_official_submissions, "Official submission requests require --allow-official-submissions")
        require("custom" not in kinds or options.allow_custom_runs, "Custom Run requests require --allow-custom-runs and approved isolated workers")
        scenario["fixture"] = fixture
        total_requests += count * (3 + len(fixture.get("setup", [])) + iterations * len(fixture["steps"]))
    require(total_seconds <= 14400 and total_requests <= 100000, "Plan exceeds4-hour/100000-request safety bounds")
    return {"maximumHttpRequests": total_requests, "maximumDurationSeconds": total_seconds, "participants": max(s["participants"] for s in plan["scenarios"])}


def render(value, variables):
    if isinstance(value, dict):
        return {str(render(k, variables)): render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    match = PLACEHOLDER.fullmatch(value)
    if match:
        require(match[1] in variables, "Unknown fixture variable")
        return variables[match[1]]
    def substitute(match):
        require(match[1] in variables, "Unknown fixture variable")
        return str(variables[match[1]])
    return PLACEHOLDER.sub(substitute, value)


def lookup(value, dotted):
    for key in dotted.split("."):
        value = value[int(key)] if isinstance(value, list) and key.isdigit() else value[key]
    return value


def percentiles(values):
    if not values:
        return {key: None for key in ("p50", "p95", "p99", "max")}
    values = sorted(values)
    def percentile(p):
        index = (len(values)-1)*p
        lower = int(index)
        return round(values[lower] + (values[min(lower+1, len(values)-1)]-values[lower])*(index-lower), 3)
    return {"p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99), "max": round(values[-1], 3)}


class Measurements:
    def __init__(self, scenario):
        self.scenario, self.lock, self.requests, self.operations = scenario, threading.Lock(), [], []
        self.started = time.monotonic()
        self.deadline = self.started + scenario["durationSeconds"]
        self.next_request = self.started

    def reserve(self):
        with self.lock:
            due = max(self.next_request, time.monotonic())
            self.next_request = due + 1/self.scenario["ratePerSecond"]
        if due >= self.deadline:
            raise Failed("duration_limit")
        time.sleep(max(0, due-time.monotonic()))

    def add(self, collection, value):
        with self.lock:
            collection.append(value)

    def report(self):
        elapsed = time.monotonic()-self.started
        codes, errors = {}, {}
        for row in self.requests:
            key = str(row["status"]) if row["status"] else "transport"
            codes[key] = codes.get(key, 0)+1
            if row["error"]:
                errors[row["error"]] = errors.get(row["error"], 0)+1
        failed = sum(not op["ok"] for op in self.operations)
        return {"name": self.scenario["name"], "configured": {k:v for k,v in self.scenario.items() if k not in ("fixture", "requestsFile")},
                "elapsedSeconds": round(elapsed, 3), "scheduledOperations": self.scenario["participants"]*self.scenario["iterations"],
                "attemptedOperations": len(self.operations), "failedOperations": failed, "durationLimitReached": time.monotonic() >= self.deadline,
                "participantsWithHttpRequests": len({row.get("actorIndex") for row in self.requests}),
                "operationLatencyMs": percentiles([op["ms"] for op in self.operations]), "operationLatencyIncludesClientPacing": True,
                "httpRequests": len(self.requests), "httpStatuses": codes, "httpErrors": errors,
                "httpLatencyMs": percentiles([row["ms"] for row in self.requests]),
                "httpRequestsPerSecond": round(len(self.requests)/elapsed, 3), "operationsPerSecond": round(len(self.operations)/elapsed, 3),
                "responseBytes": sum(row["bytes"] for row in self.requests),
                "officialOutcomeUnknown": sum(row["officialUnknown"] for row in self.requests),
                "queueAgeSeconds": None, "databaseConnections": None, "storageGrowthBytes": None,
                "serverCpuPercent": None, "serverMemoryBytes": None,
                "metricsNote": "Server/queue/storage metrics are not collected; collect separate trusted host/database measurements."}


class Actor:
    def __init__(self, index, entry, target):
        self.index, self.entry, self.target = index, entry, target
        self.context, self.client, self.expected_principal = None, None, None
        self.variables = dict(entry.get("variables", {}), taskId=entry["taskId"], participantIndex=index)
        self.setups = set()

    def close(self):
        if self.client:
            self.client.close()

    def request(self, measure, method, path, *, payload=None, form=None, expected=(200,), phase="operation"):
        measure.reserve()
        local_path(path)
        headers = {}
        if self.context:
            headers = {"X-Olympiad-Principal": self.context["identity"]["principalId"], "X-XSRFToken": self.context["csrfToken"], "X-Olympiad-Task": str(self.entry["taskId"])}
        started = time.monotonic()
        status, size, error, value = None, 0, None, None
        official = method == "POST" and path == "/ide/api/submissions"
        try:
            timeout = min(measure.scenario.get("timeoutSeconds", 10), max(.1, measure.deadline-time.monotonic()))
            raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode() if payload is not None else None
            if raw is not None:
                require(len(raw) <= MAX_BODY, "Rendered request exceeds byte limit")
                headers["Content-Type"] = "application/json"
            with self.client.request(method, self.target["origin"].rstrip("/")+path, headers=headers,
                    data=form if form is not None else raw, timeout=(min(2, timeout), timeout), allow_redirects=False, stream=True) as response:
                status = response.status_code
                chunks = bytearray()
                for chunk in response.iter_content(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_BODY or time.monotonic() > measure.deadline:
                        raise Failed("response_bound")
                size = len(chunks)
                if "application/json" in response.headers.get("Content-Type", ""):
                    value = json.loads(chunks)
                if status not in expected:
                    raise Failed("http_"+str(status))
                if status >= 400:
                    error = "expected_http_"+str(status)
        except requests.RequestException as exc:
            error = type(exc).__name__
        except (ValueError, Failed) as exc:
            error = str(exc) if isinstance(exc, Failed) else "invalid_response_or_fixture"
        finally:
            measure.add(measure.requests, {"ms": (time.monotonic()-started)*1000, "status": status, "bytes": size,
                "actorIndex": self.index, "phase": phase, "error": error, "officialUnknown": bool(official and (status is None or status >= 500 or (error and status < 400)))})
        if error and not error.startswith("expected_http_"):
            raise Failed(error)
        return value

    def context_check(self, value):
        require(isinstance(value, dict) and value.get("schemaVersion") == 1, "Unsupported CMS context")
        identity = value["identity"]
        require(identity["installationId"] == self.target["installationId"] and int(identity["contestId"]) == self.target["contestId"], "Target identity scope mismatch")
        require(value["contest"]["name"] == self.target["contestName"] and value["user"]["username"] == self.entry["username"], "Disposable contest or participant mismatch")
        require(isinstance(value.get("csrfToken"), str) and self.entry["taskId"] in [t["id"] for t in value["tasks"]], "Selected disposable task unavailable")
        if self.expected_principal:
            require(identity["principalId"] == self.expected_principal, "Participant identity changed; stopping actor")
        self.expected_principal = identity["principalId"]
        self.context = value
        self.variables["principalId"] = identity["principalId"]

    def login(self, measure):
        self.close()
        self.context = None
        self.client = requests.Session()
        self.client.trust_env = False
        self.client.verify = self.target.get("caBundle") or True
        base = self.target.get("cwsBasePath", "/")
        self.request(measure, "GET", base, phase="authentication")
        xsrf = self.client.cookies.get("_xsrf")
        require(bool(xsrf), "CWS did not establish its CSRF cookie")
        self.request(measure, "POST", base+"login", form={"username": self.entry["username"], "password": self.entry["password"], "_xsrf": xsrf}, expected=(302,), phase="authentication")
        value = self.request(measure, "GET", "/ide/api/context", phase="authentication")
        self.context_check(value)

    def step(self, measure, step):
        for name in step.get("newIds", []):
            self.variables[name] = str(uuid4())
        # Encode variables in paths; body values retain their JSON types/bytes.
        path = render(step["path"], {k: quote(str(v), safe="") for k,v in self.variables.items()})
        category(step["method"], path)
        value = self.request(measure, step["method"], path, payload=render(step.get("json"), self.variables), expected=step.get("expect", [200]))
        for key, expected in step.get("assert", {}).items():
            require(lookup(value, key) == render(expected, self.variables), "Response assertion failed")
        for name, dotted in step.get("capture", {}).items():
            self.variables[name] = lookup(value, dotted)

    def run(self, measure):
        scenario = measure.scenario
        due = measure.started+scenario["rampSeconds"]*self.index/max(1, scenario["participants"]-1)
        time.sleep(max(0, due-time.monotonic()))
        if time.monotonic() >= measure.deadline:
            return
        try:
            if scenario["name"] != "login_burst" and self.context is None:
                self.login(measure)
            fixture = scenario["fixture"]
            for name in fixture.get("actorIds", []):
                self.variables.setdefault(name, str(uuid4()))
            key = scenario.get("requestsFile")
            if key and key not in self.setups:
                self.variables["iteration"] = 0
                for step in fixture.get("setup", []):
                    self.step(measure, step)
                self.setups.add(key)
        except (Invalid, Failed, KeyError, TypeError, IndexError):
            measure.add(measure.operations, {"ok": False, "ms": 0, "phase": "setup"})
            return
        for iteration in range(scenario["iterations"]):
            if time.monotonic() >= measure.deadline:
                return
            self.variables["iteration"] = iteration
            started, ok = time.monotonic(), False
            try:
                if scenario["name"] == "login_burst":
                    self.login(measure)
                elif scenario["name"] == "context_read":
                    self.context_check(self.request(measure, "GET", "/ide/api/context"))
                else:
                    for step in fixture["steps"]:
                        self.step(measure, step)
                ok = True
            except (Invalid, Failed, KeyError, TypeError, IndexError):
                # No automatic replay, especially after an unknown official POST.
                pass
            measure.add(measure.operations, {"ok": ok, "ms": (time.monotonic()-started)*1000, "phase": "operation"})
            if not ok:
                return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="External disposable-target JSON")
    parser.add_argument("--credentials", required=True, help="External mode0600 disposable credentials JSON")
    parser.add_argument("--plan", required=True, help="External progressive scenario JSON")
    parser.add_argument("--report", required=True, help="New output JSON path; never includes credentials or source bodies")
    parser.add_argument("--confirm-disposable", required=True, help="Exact targetId from disposable target manifest")
    parser.add_argument("--allow-remote-disposable", action="store_true")
    parser.add_argument("--allow-official-submissions", action="store_true")
    parser.add_argument("--allow-custom-runs", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Validate all external files without making any HTTP request")
    args = parser.parse_args(argv)
    try:
        target, credentials, plan = read_json(args.target), read_json(args.credentials, private=True), read_json(args.plan)
        summary = validate(target, credentials, plan, args)
        report = Path(args.report).expanduser().resolve()
        require(not report.exists(), "Report path already exists; choose a new path")
        document = {"schemaVersion": 1, "kind": "cms-progressive-load", "startedAt": datetime.now(timezone.utc).isoformat(),
            "validation": summary, "execution": "validation_only" if args.validate_only else "measured",
            "target": {key:target[key] for key in ("targetId", "origin", "installationId", "contestId", "contestName")},
            "metadata": {"runner": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version(), "cpuCount": os.cpu_count()},
                         "serverHardware": target.get("serverHardware"), "toolchains": target.get("toolchains"), "testSuiteCost": target.get("testSuiteCost"),
                         "participantProgramExecutionsVerified": False},
            "scenarios": [], "capacityClaim": "None. Only executed scenarios are measurements;350 participants remain untested unless explicitly measured here."}
        actors = [Actor(i, row, target) for i,row in enumerate(credentials)]
        try:
            if not args.validate_only:
                for scenario in plan["scenarios"]:
                    measure = Measurements(scenario)
                    with ThreadPoolExecutor(max_workers=scenario["concurrency"]) as executor:
                        futures = [executor.submit(actor.run, measure) for actor in actors[:scenario["participants"]]]
                        for future in futures:
                            future.result()
                    document["scenarios"].append(measure.report())
        finally:
            for actor in actors:
                actor.close()
        document["finishedAt"] = datetime.now(timezone.utc).isoformat()
        with report.open("x", encoding="utf-8") as stream:
            os.chmod(report, 0o600)
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"execution": document["execution"], "scenarios": len(document["scenarios"]), "report": str(report), **summary}))
        return 1 if any(row["failedOperations"] for row in document["scenarios"]) else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Never echo filenames, parsed body data, credentials or response text.
        detail = str(error) if isinstance(error, Invalid) else type(error).__name__
        parser.exit(2, "Load configuration or execution failed: %s.\n" % detail)


if __name__ == "__main__":
    raise SystemExit(main())
