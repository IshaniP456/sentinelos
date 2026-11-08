"""Two-phase container restart acceptance check, local only. Author: Tishneet.

Run prepare, restart DynamoDB/API/worker containers, then run verify. The check's
plan reference is itself durable so no browser or container memory is needed.
"""
import argparse
import json

from backend.workflows.factory import create_service
from scripts.demo import request, wait, counts, D2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "verify"])
    parser.add_argument("--base", default="http://localhost:8000/v1")
    args = parser.parse_args()
    service = create_service(runtime="local")
    if args.phase == "prepare":
        request(args.base, "POST", "/demo/reset", {})
        plan_id = request(args.base, "POST", "/plans", {"instruction": D2})["plan_id"]
        status = wait(args.base, plan_id, {"AWAITING_APPROVAL"})
        value = {"plan_id": plan_id, "approval_id": status["approval"]["approval_id"],
                 "warehouse": request(args.base, "GET", "/warehouse")}
        version, _ = service.store.read("CHECK#restart")
        service.store.write("CHECK#restart", value, version)
        print(json.dumps({"phase": "prepared", "plan_id": plan_id, "status": status["status"]}))
    else:
        _, value = service.store.read("CHECK#restart")
        assert value, "Run prepare first"
        plan_id = value["plan_id"]
        status = request(args.base, "GET", "/plans/" + plan_id)
        assert status["status"] == "AWAITING_APPROVAL"
        assert status["approval"]["approval_id"] == value["approval_id"]
        assert request(args.base, "GET", "/warehouse") == value["warehouse"]
        path = "/approvals/" + value["approval_id"]
        request(args.base, "POST", path, {"decision": "APPROVED"})
        wait(args.base, plan_id, {"COMPLETED"})
        before = request(args.base, "GET", "/warehouse")
        request(args.base, "POST", path, {"decision": "APPROVED"})
        assert request(args.base, "GET", "/warehouse") == before
        assert counts(before) == {"A": 15, "B": 10, "C": 8} and before["version"] == 2
        print(json.dumps({"phase": "verified", "result": "PASS", "pending_approval_survived": True,
                          "duplicate_execution": False, "version": before["version"]}))


if __name__ == "__main__":
    main()
