"""kubectl-style command-line interface for Hydra Jobs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import yaml

from cli import __version__
from cli._client import APIError, HydraClient
from cli._output import write_document, write_error, write_table

TABLES = {
    "jobs": [("NAME", "name"), ("ID", "_display_id"), ("SCHEDULE", "_schedule"), ("ENABLED", "enabled"), ("DOMAIN", "domain")],
    "runs": [("RUN", "_display_id"), ("JOB", "job_id"), ("STATUS", "status"), ("WORKER", "worker_id"), ("STARTED", "start_ts")],
    "workers": [
        ("WORKER", "_display_id"),
        ("DOMAIN", "domain"),
        ("CONNECTIVITY", "connectivity_status"),
        ("STATE", "dispatch_status"),
        ("RUNNING", "current_running"),
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hydra-ctl", description="Operate a Hydra Jobs deployment")
    parser.add_argument("--api-url", default=os.getenv("HYDRA_API_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("HYDRA_TOKEN") or os.getenv("API_TOKEN"))
    parser.add_argument("--domain", default=os.getenv("HYDRA_DOMAIN") or os.getenv("DOMAIN"))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument("-o", "--output", choices=("table", "json", "yaml"), default="table")

    get = commands.add_parser("get", parents=[output_parent], help="List or fetch resources")
    get.add_argument("resource", choices=("jobs", "runs", "workers"))
    get.add_argument("name", nargs="?")
    get.add_argument("--search")
    get.add_argument("--limit", type=int, default=100)

    describe = commands.add_parser("describe", parents=[output_parent], help="Show one resource")
    describe.add_argument("resource", choices=("job", "run", "worker"))
    describe.add_argument("name")

    logs = commands.add_parser("logs", help="Print a run's logs")
    logs.add_argument("run_id")
    logs.add_argument("-f", "--follow", action="store_true")

    run = commands.add_parser("run", parents=[output_parent], help="Trigger a job")
    run.add_argument("job")
    run.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")

    apply = commands.add_parser("apply", parents=[output_parent], help="Create a job from YAML or JSON")
    apply.add_argument("-f", "--filename", required=True)

    validate = commands.add_parser("validate", parents=[output_parent], help="Validate a job YAML or JSON document")
    validate.add_argument("-f", "--filename", required=True)

    delete = commands.add_parser("delete", parents=[output_parent], help="Delete a resource")
    delete.add_argument("resource", choices=("job",))
    delete.add_argument("name")

    kill = commands.add_parser("kill", parents=[output_parent], help="Terminate a run")
    kill.add_argument("run_id")

    backfill = commands.add_parser("backfill", parents=[output_parent], help="Backfill a scheduled job")
    backfill.add_argument("job")
    backfill.add_argument("--from", dest="from_time", required=True)
    backfill.add_argument("--to", dest="to_time", required=True)

    worker = commands.add_parser("worker", parents=[output_parent], help="Manage workers")
    worker_commands = worker.add_subparsers(dest="worker_command", required=True)
    state = worker_commands.add_parser("state", parents=[output_parent], help="Set dispatch state")
    state.add_argument("worker_id")
    state.add_argument("state", choices=("online", "draining", "offline"))
    detach = worker_commands.add_parser("detach", parents=[output_parent], help="Detach a worker")
    detach.add_argument("worker_id")

    overview = commands.add_parser("overview", parents=[output_parent], help="Show cluster health")
    overview.add_argument("view", nargs="?", default="statistics", choices=("statistics", "queue", "pressure"))

    token = commands.add_parser("token", parents=[output_parent], help="Manage the current domain token")
    token_commands = token.add_subparsers(dest="token_command", required=True)
    token_commands.add_parser("rotate", parents=[output_parent], help="Rotate the current domain token")
    return parser


def main(argv: list[str] | None = None, client_factory: type[HydraClient] = HydraClient) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = client_factory(args.api_url, token=args.token, domain=args.domain, timeout=args.timeout)
    try:
        if args.command == "get":
            return _get(client, args)
        if args.command == "describe":
            return _describe(client, args)
        if args.command == "logs":
            return _logs(client, args)
        if args.command == "run":
            job_id = _resolve_job(client, args.job)
            _show(client.request("POST", f"/jobs/{_quote(job_id)}/run", body={"params": _params(args.param)}), args.output)
        elif args.command == "apply":
            document = _load_document(args.filename)
            _show(client.submit(document), args.output)
        elif args.command == "validate":
            document = _load_document(args.filename)
            _show(client.validate(document), args.output)
        elif args.command == "delete":
            job_id = _resolve_job(client, args.name)
            _show(client.request("DELETE", f"/jobs/{_quote(job_id)}"), args.output)
        elif args.command == "kill":
            _show(client.request("POST", f"/runs/{_quote(args.run_id)}/kill"), args.output)
        elif args.command == "backfill":
            job_id = _resolve_job(client, args.job)
            body = {"start_date": args.from_time, "end_date": args.to_time}
            _show(client.request("POST", f"/jobs/{_quote(job_id)}/backfill", body=body), args.output)
        elif args.command == "worker":
            path = f"/workers/{_quote(args.worker_id)}/{args.worker_command}"
            body = {"state": args.state} if args.worker_command == "state" else None
            _show(client.request("POST", path, body=body), args.output)
        elif args.command == "overview":
            _show(client.request("GET", f"/overview/{args.view}"), args.output)
        elif args.command == "token":
            _show(client.rotate_token(), args.output)
        return 0
    except (APIError, OSError, ValueError, yaml.YAMLError) as exc:
        write_error(str(exc))
        return 1


def _get(client: HydraClient, args: argparse.Namespace) -> int:
    if args.name:
        singular = args.resource.removesuffix("s")
        return _describe(client, argparse.Namespace(resource=singular, name=args.name, output=args.output))
    path = {"jobs": "/jobs/", "runs": "/history/", "workers": "/workers/"}[args.resource]
    query = {"limit": args.limit, "search": args.search} if args.resource != "workers" else None
    payload = client.request("GET", path, query=query)
    rows = _items(payload, args.resource)
    if args.output != "table":
        write_document(payload, args.output)
    else:
        write_table((_display_row(item, args.resource) for item in rows), TABLES[args.resource])
    return 0


def _describe(client: HydraClient, args: argparse.Namespace) -> int:
    if args.resource == "job":
        item = client.request("GET", f"/jobs/{_quote(_resolve_job(client, args.name))}")
    elif args.resource == "run":
        item = client.request("GET", f"/runs/{_quote(args.name)}")
    else:
        workers = _items(client.request("GET", "/workers/"), "workers")
        item = next((worker for worker in workers if str(_id(worker)) == args.name), None)
        if item is None:
            raise APIError(f"worker {args.name!r} was not found", 404)
    write_document(item, "yaml" if args.output == "table" else args.output)
    return 0


def _logs(client: HydraClient, args: argparse.Namespace) -> int:
    if args.follow:
        for event, payload in client.stream_sse(f"/runs/{_quote(args.run_id)}/stream"):
            if event == "log_chunk" and isinstance(payload, dict):
                print(payload.get("text", ""), end="", flush=True)
            elif event in {"error", "run_error"}:
                write_error(str(payload))
        return 0
    run = client.request("GET", f"/runs/{_quote(args.run_id)}")
    stdout = run.get("stdout") or ""
    stderr = run.get("stderr") or ""
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    return 0


def _resolve_job(client: HydraClient, value: str) -> str:
    try:
        job = client.request("GET", f"/jobs/{_quote(value)}")
        return str(_id(job))
    except APIError as exc:
        if exc.status != 404:
            raise
    matches = _items(client.request("GET", "/jobs/", query={"search": value, "limit": 100}), "jobs")
    exact = [job for job in matches if job.get("name") == value]
    if len(exact) == 1:
        return str(_id(exact[0]))
    if not exact:
        raise APIError(f"job {value!r} was not found", 404)
    raise APIError(f"job name {value!r} is ambiguous; use its ID")


def _load_document(filename: str) -> dict[str, Any]:
    text = sys.stdin.read() if filename == "-" else Path(filename).read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError("job definition must be a YAML or JSON object")
    return document


def _params(entries: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"invalid parameter {entry!r}; expected KEY=VALUE")
        key, value = entry.split("=", 1)
        if not key:
            raise ValueError("parameter name cannot be empty")
        try:
            result[key] = json.loads(value)
        except json.JSONDecodeError:
            result[key] = value
    return result


def _items(payload: Any, resource: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (resource, "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise APIError(f"unexpected response shape for {resource}")


def _display_row(item: dict[str, Any], resource: str) -> dict[str, Any]:
    row = dict(item)
    row["_display_id"] = _id(item)
    schedule = item.get("schedule")
    if resource == "jobs" and isinstance(schedule, dict):
        row["_schedule"] = schedule.get("cron") or schedule.get("mode") or schedule.get("interval_seconds")
    return row


def _id(item: dict[str, Any]) -> Any:
    return item.get("_id") or item.get("id") or item.get("worker_id")


def _quote(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="")


def _show(payload: Any, output: str) -> None:
    write_document(payload, "yaml" if output == "table" else output)


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
