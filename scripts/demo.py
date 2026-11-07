"""Verify canonical D1/D2/D3 through the running HTTP API. Author: Tishneet.

Local fixture stack only. Approval/revoke/reset require its explicit open-dev
mode, or a dev token supplied in SENTINEL_ADMIN_TOKEN. No AWS writes occur here.
"""
import argparse
import json
import os
import time
from urllib.request import Request, urlopen

D1 = "Move three packages from Zone A to Zone C."
D2 = "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary."
D3 = "Move one package from Zone A to Zone C."


def request(base, method, path, data=None):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("SENTINEL_ADMIN_TOKEN"):
        headers["X-Admin-Token"] = os.environ["SENTINEL_ADMIN_TOKEN"]
    body = None if data is None else json.dumps(data).encode()
    with urlopen(Request(base + path, data=body, headers=headers, method=method), timeout=10) as response:
        return json.load(response)


def wait(base, plan_id, targets):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status = request(base, "GET", "/plans/" + plan_id)
        if status["status"] in targets:
            return status
        if status["status"] in {"FAILED", "REJECTED", "EXPIRED"}:
            raise AssertionError("Unexpected terminal outcome: " + json.dumps(status.get("error")))
        time.sleep(0.2)
    raise AssertionError("Workflow did not reach expected status before deadline")


def counts(warehouse):
    return {zone: values["inventory"] for zone, values in warehouse["zones"].items()}


def walkthrough(base):
    seed = request(base, "POST", "/demo/reset", {})
    assert counts(seed) == {"A": 20, "B": 8, "C": 5} and seed["version"] == 1
    first = request(base, "POST", "/plans", {"instruction": D1})["plan_id"]
    one = wait(base, first, {"COMPLETED"})
    assert one["risk"]["approval_required"] is False
    actual = request(base, "GET", "/warehouse")
    assert counts(actual) == {"A": 17, "B": 8, "C": 8} and actual["version"] == 2
    second = request(base, "POST", "/plans", {"instruction": D2})["plan_id"]
    two = wait(base, second, {"AWAITING_APPROVAL"})
    assert two["attempt"] == 2 and len(two["candidates"]) == 2
    assert two["candidates"][0]["simulation"]["passed"] is False
    assert two["candidates"][0]["simulation"]["projected_state"]["B"]["inventory"] == 13
    assert two["risk"]["total_packages"] == 5
    assert request(base, "GET", "/warehouse") == actual, "Projection changed actual inventory"
    approval_path = "/approvals/" + two["approval"]["approval_id"]
    request(base, "POST", approval_path, {"decision": "APPROVED"})
    request(base, "POST", approval_path, {"decision": "APPROVED"})
    wait(base, second, {"COMPLETED"})
    final = request(base, "GET", "/warehouse")
    assert counts(final) == {"A": 12, "B": 10, "C": 11} and final["version"] == 3
    request(base, "POST", "/agents/current/revoke", {})
    third = request(base, "POST", "/plans", {"instruction": D3})["plan_id"]
    wait(base, third, {"REJECTED"})
    assert request(base, "GET", "/warehouse") == final
    events = request(base, "GET", "/audit?plan_id=" + second)["events"]
    expected = {"VALIDATION_PASSED", "AUTHORIZATION_ALLOWED", "SIMULATION_FAILED", "REPLAN_GENERATED",
                "SIMULATION_PASSED", "RISK_CLASSIFIED", "AWAITING_APPROVAL", "APPROVAL_APPROVED", "PLAN_EXECUTED"}
    assert expected <= {event["event_type"] for event in events}
    assert sum(event["event_type"] == "PLAN_EXECUTED" for event in events) == 1
    return {"result": "PASS", "provider": two["runtime"], "counts": counts(final), "version": final["version"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000/v1")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    for run in range(args.runs):
        print(json.dumps({"run": run + 1, **walkthrough(args.base)}), flush=True)


if __name__ == "__main__":
    main()
