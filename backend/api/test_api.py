"""Exercise the real HTTP handlers through the three judged demos (D1/D2/D3).

Run:  python -m backend.api.test_api
No external deps; uses the LocalBackendOps reference backend.
"""

import json
import os
import time

# Configure dev admin auth before importing modules that read the env.
os.environ.setdefault("SENTINEL_BACKEND", "local")
os.environ["SENTINEL_AUTH_MODE"] = "dev"
os.environ["SENTINEL_ADMIN_TOKEN"] = "devtoken"

import backend.api.backend_ops as backend_ops  # noqa: E402
from backend.api.handlers import handler  # noqa: E402

ADMIN = {"X-Admin-Token": "devtoken"}
_fails = []


def call(method, path, body=None, headers=None):
    event = {
        "httpMethod": method, "path": path,
        "headers": headers or {}, "body": json.dumps(body) if body is not None else "",
        "queryStringParameters": None,
    }
    resp = handler(event, None)
    parsed = json.loads(resp["body"]) if resp.get("body") else None
    return resp["statusCode"], parsed


def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        _fails.append(name)


def zones(w):
    return {k: v["inventory"] for k, v in w["zones"].items()}


def wait_status(plan_id, target, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, s = call("GET", f"/v1/plans/{plan_id}")
        if s["status"] == target:
            return s
        time.sleep(0.1)
    _, s = call("GET", f"/v1/plans/{plan_id}")
    raise AssertionError(f"timeout waiting {target}, got {s['status']}")


def reset():
    backend_ops._SINGLETON = None  # fresh backend per scenario group


print("== routing / basics ==")
st, w = call("GET", "/v1/warehouse")
check("GET /warehouse 200", st == 200)
check("seed A=20 B=8 C=5 v1", zones(w) == {"A": 20, "B": 8, "C": 5} and w["version"] == 1)
st, a = call("GET", "/v1/agents/current")
check("GET /agents/current ACTIVE", st == 200 and a["status"] == "ACTIVE")
st, _ = call("GET", "/v1/nope")
check("unknown route 404", st == 404)
st, e = call("POST", "/v1/plans", {})
check("empty instruction 400 + error obj", st == 400 and e["error"]["code"] == "INVALID_REQUEST")

print("== D1 low-risk auto-execute ==")
st, r = call("POST", "/v1/plans", {"instruction": "Move three packages from Zone A to Zone C."})
check("POST /plans 202 PLANNING", st == 202 and r["status"] == "PLANNING")
wait_status(r["plan_id"], "COMPLETED")
_, w = call("GET", "/v1/warehouse")
check("D1 -> A=17 B=8 C=8 v2", zones(w) == {"A": 17, "B": 8, "C": 8} and w["version"] == 2)

print("== D2 reject -> replan -> approval ==")
st, r = call("POST", "/v1/plans",
             {"instruction": "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary."})
s = wait_status(r["plan_id"], "AWAITING_APPROVAL")
check("two candidates shown", len(s["candidates"]) == 2)
check("rev1 simulation failed", s["candidates"][0]["simulation"]["passed"] is False)
check("rev2 simulation passed", s["candidates"][1]["simulation"]["passed"] is True)
check("risk ELEVATED total 5", s["risk"]["risk"] == "ELEVATED" and s["risk"]["total_packages"] == 5)
_, w = call("GET", "/v1/warehouse")
check("inventory unchanged before approval (v2)", w["version"] == 2)
# Approval requires admin.
st, _ = call("POST", f"/v1/approvals/{s['approval']['approval_id']}", {"decision": "APPROVED"})
check("approval without admin -> 403", st == 403)
st, r2 = call("POST", f"/v1/approvals/{s['approval']['approval_id']}", {"decision": "APPROVED"}, ADMIN)
check("approval with admin -> 202 RECORDED", st == 202 and r2["status"] == "RECORDED")
wait_status(r["plan_id"], "COMPLETED")
_, w = call("GET", "/v1/warehouse")
check("D2 -> A=12 B=10 C=11 v3", zones(w) == {"A": 12, "B": 10, "C": 11} and w["version"] == 3)

print("== D3 revocation blocks subsequent request ==")
st, _ = call("POST", "/v1/agents/current/revoke", {})
check("revoke without admin -> 403", st == 403)
st, a = call("POST", "/v1/agents/current/revoke", {}, ADMIN)
check("revoke with admin -> REVOKED", st == 200 and a["status"] == "REVOKED")
st, r = call("POST", "/v1/plans", {"instruction": "Move one package from Zone A to Zone C."})
s = wait_status(r["plan_id"], "REJECTED")
check("post-revoke request REJECTED (AGENT_REVOKED)",
      s["candidates"][0]["authorization"]["decisions"][0]["reason_code"] == "AGENT_REVOKED")
_, w = call("GET", "/v1/warehouse")
check("D3 inventory unchanged v3", zones(w) == {"A": 12, "B": 10, "C": 11} and w["version"] == 3)

print("== reset guard (FR13) ==")
reset()
st, r = call("POST", "/v1/plans",
             {"instruction": "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary."})
wait_status(r["plan_id"], "AWAITING_APPROVAL")
st, e = call("POST", "/v1/demo/reset", {}, ADMIN)
check("reset blocked while plan active -> 409", st == 409 and e["error"]["code"] == "VERSION_CONFLICT")

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    raise SystemExit(1)
print("ALL PASS")
