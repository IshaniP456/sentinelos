"""Latency of each SentinelOS stage.

Local (default): times the pure stages in-process, no AWS.
    python -m evidence.latency

Deployed (--aws): times round trips to the deployed Lambdas from wherever you
run it (for example the workshop VS Code), so network time is included.
Read-only by default:
    python -m evidence.latency --aws
      * sentinel-data-warehouse     read the warehouse
      * sentinel-security-authorize policy check through Verified Permissions

Opt-in, still no writes:
    python -m evidence.latency --aws --include-execute
      * sentinel-data-execute with a probe plan that runs every check
        (replay marker, state read, Verified Permissions, approval rule) and
        is refused at the final simulation step, so nothing is committed.
        The probe is chosen from the live state and confirmed to fail locally
        before it is sent. Run it when nobody is mid-demo.

Prints a markdown table: calls, median, p95 and max in milliseconds. The
first two calls per stage warm the Lambda and are not counted.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from typing import Any, Callable

from core.fingerprint import plan_fingerprint
from core.simulator import simulate_plan
from data.schema import seed_agent, seed_warehouse
from security.authorization import authorize_plan

D1 = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]}
SPLIT = {"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 2},
                     {"type": "move_packages", "from": "A", "to": "C", "count": 3}]}
WARMUP = 2
NO_APPROVAL_MAX = 4  # plans moving 5+ packages need an approval, which would stop the probe early


def measure(fn: Callable[[], Any], n: int, warmup: int = 0) -> list[float]:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def row(stage: str, samples: list[float]) -> str:
    ordered = sorted(samples)
    p95 = ordered[max(0, round(0.95 * len(ordered)) - 1)]
    return (f"| {stage} | {len(samples)} | {statistics.median(ordered):.3f} | {p95:.3f} | {ordered[-1]:.3f} |")


def local(n: int) -> list[str]:
    warehouse, agent = seed_warehouse(), seed_agent()
    return [
        row("Fingerprint plan (in-process)", measure(lambda: plan_fingerprint(SPLIT), n)),
        row("Simulate plan (in-process)", measure(lambda: simulate_plan(SPLIT, warehouse), n)),
        row("Local policy check (in-process)", measure(lambda: authorize_plan(SPLIT, agent, ["HAZMAT"]), n)),
    ]


def probe_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    """A no-approval plan that the CURRENT state is guaranteed to reject at simulation."""
    zones = state["zones"]
    for dest, z in zones.items():
        room = z["capacity"] - z["inventory"]
        k = room + 1
        if k > NO_APPROVAL_MAX:
            continue
        for src, s in zones.items():
            if src != dest and s["inventory"] >= k:
                candidate = {"actions": [{"type": "move_packages", "from": src, "to": dest, "count": k}]}
                if not simulate_plan(candidate, state)["passed"]:
                    return candidate
    return None


def deployed(n: int, region: str, include_execute: bool) -> list[str]:
    import boto3

    client = boto3.client("lambda", region_name=region)

    def invoke(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = client.invoke(FunctionName=name, Payload=json.dumps(payload).encode())["Payload"].read()
        return json.loads(body)

    rows = [row("Read warehouse (Lambda round trip)",
                measure(lambda: invoke("sentinel-data-warehouse", {}), n, WARMUP))]

    check = invoke("sentinel-security-authorize", {"plan": D1})
    if check.get("engine") != "VERIFIED_PERMISSIONS":
        print(f"Note: authorize answered with engine {check.get('engine')!r}", file=sys.stderr)
    rows.append(row("Policy check via Verified Permissions (Lambda round trip)",
                    measure(lambda: invoke("sentinel-security-authorize", {"plan": D1}), n, WARMUP)))

    if include_execute:
        state = invoke("sentinel-data-warehouse", {})
        run_id = invoke("sentinel-data-runid", {}).get("run_id")
        probe = probe_plan(state)
        if probe is None or not isinstance(run_id, str):
            print("Skipped execute: no probe plan is guaranteed to fail on the current state.", file=sys.stderr)
            return rows

        def execute_probe() -> None:
            result = invoke("sentinel-data-execute", {
                "plan_id": f"latency-probe-{uuid.uuid4().hex[:12]}", "revision": 1, "plan": probe,
                "warehouse_version": state["version"], "run_id": run_id, "approval": None})
            if result.get("executed") is not False or not result.get("no_commit"):
                raise SystemExit(f"Stopping: execute probe did not return a guaranteed no-commit: {result}")

        rows.append(row("Full executor checks, refused at simulation (Lambda round trip)",
                        measure(execute_probe, n, WARMUP)))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time each SentinelOS stage.")
    parser.add_argument("--aws", action="store_true", help="also time the deployed Lambdas (read-only)")
    parser.add_argument("--include-execute", action="store_true",
                        help="with --aws, also time the executor using a probe plan that cannot commit")
    parser.add_argument("-n", type=int, default=None, help="calls per stage (default 2000 local, 20 AWS)")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    lines = ["| Stage | Calls | Median ms | p95 ms | Max ms |", "|---|---|---|---|---|"]
    lines += local(args.n or 2000)
    if args.aws:
        lines += deployed(args.n or 20, args.region, args.include_execute)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
