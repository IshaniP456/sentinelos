"""Tests for the signed admin assertion (Mariam's revoke/reset contract).

Run:  python -m backend.api.test_admin_assertion
No real AWS: the Lambda client is a fake and the signing key is pre-cached.
"""

import json
import os

os.environ["REVOKE_FN"] = "sentinel-data-revoke"
os.environ["RESET_FN"] = "sentinel-data-reset"

from backend.api.backend_ops import AwsBackendOps, build_admin_assertion  # noqa: E402
from backend.api.responses import ApiError  # noqa: E402

_fails = []


def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        _fails.append(name)


class FakeLambda:
    """Records invocations and returns a canned JSON body."""

    def __init__(self, response_obj):
        self.calls = []  # list of (FunctionName, parsed_payload)
        self._body = json.dumps(response_obj).encode()

    def invoke(self, FunctionName, Payload):
        self.calls.append((FunctionName, json.loads(Payload)))
        body = self._body

        class _P:
            def read(self):
                return body

        return {"Payload": _P()}


class NoInvokeLambda:
    def invoke(self, **_):
        raise AssertionError("Lambda must NOT be invoked")


def make_ops(secret_arn="arn:aws:secretsmanager:us-east-1:737876441172:secret:sentinel/admin-assertion-key-Q0mVDN",
             key=b"k" * 64, lam=None):
    ops = AwsBackendOps.__new__(AwsBackendOps)  # bypass __init__ (no real boto3)
    ops._lambda = lam
    ops._sfn = None
    ops._state_machine = None
    ops._agent_id = "inventory-agent-01"
    ops._admin_secret_arn = secret_arn
    ops._admin_key = key  # pre-cache so no SecretsManager call
    return ops


print("== known-answer (matches Mariam's real verifier) ==")
KEY = b"k" * 64
A = build_admin_assertion(KEY, "REVOKE_AGENT", "alice@scu.edu", 1762548000, "0123456789abcdef0123456789abcdef")
check("REVOKE_AGENT signature", A["signature"] == "2056947d2ec66e5153a00b09e842edcff1679e5f3244ef1c344f30554dd67422")
B = build_admin_assertion(KEY, "RESET_DEMO", "alice@scu.edu", 1762548000, "0123456789abcdef0123456789abcdef")
check("RESET_DEMO signature", B["signature"] == "9b747a8f28f598f662001e5d36a8d65c4cf5e220fd7ce87a678927f0b426d5b7")
check("exactly five fields", set(A.keys()) == {"admin", "action", "issued_at", "nonce", "signature"})

print("== revoke/reset send a correct assertion ==")
lam = FakeLambda({"agent_id": "inventory-agent-01", "status": "REVOKED", "role": "INVENTORY_MANAGER", "max_transfer": 10})
ops = make_ops(lam=lam)
ops.revoke_agent("alice@scu.edu")
fn, payload = lam.calls[0]
check("revoke invokes REVOKE_FN", fn == "sentinel-data-revoke")
check("payload is {admin_assertion: {...}}", list(payload.keys()) == ["admin_assertion"])
asrt = payload["admin_assertion"]
check("assertion has exactly five fields", set(asrt.keys()) == {"admin", "action", "issued_at", "nonce", "signature"})
check("revoke action is REVOKE_AGENT", asrt["action"] == "REVOKE_AGENT")
check("admin passed through", asrt["admin"] == "alice@scu.edu")
check("issued_at is int", isinstance(asrt["issued_at"], int))
check("nonce is 32 hex", len(asrt["nonce"]) == 32 and all(c in "0123456789abcdef" for c in asrt["nonce"]))

lam2 = FakeLambda({"warehouse_id": "demo-warehouse", "version": 1, "zones": {}, "restricted_zones": ["HAZMAT"]})
ops2 = make_ops(lam=lam2)
ops2.reset_demo("alice@scu.edu")
check("reset action is RESET_DEMO", lam2.calls[0][1]["admin_assertion"]["action"] == "RESET_DEMO")

print("== fresh nonce every call (single-use) ==")
lam3 = FakeLambda({"status": "REVOKED"})
ops3 = make_ops(lam=lam3)
ops3.revoke_agent("alice@scu.edu")
ops3.revoke_agent("alice@scu.edu")
n1 = lam3.calls[0][1]["admin_assertion"]["nonce"]
n2 = lam3.calls[1][1]["admin_assertion"]["nonce"]
check("two calls use different nonces", n1 != n2)

print("== fail closed ==")
no_secret = make_ops(secret_arn=None, key=None, lam=NoInvokeLambda())
try:
    no_secret.revoke_agent("alice@scu.edu")
    check("missing ADMIN_SECRET_ARN -> INTERNAL_ERROR", False)
except ApiError as e:
    check("missing ADMIN_SECRET_ARN -> INTERNAL_ERROR (no invoke)", e.code == "INTERNAL_ERROR" and e.status == 500)

bad_admin = make_ops(lam=NoInvokeLambda())
try:
    bad_admin.revoke_agent("ev|il")
    check("admin with '|' -> FORBIDDEN", False)
except ApiError as e:
    check("admin with '|' -> FORBIDDEN (no invoke)", e.code == "FORBIDDEN")

try:
    make_ops(lam=NoInvokeLambda()).reset_demo("")
    check("empty admin -> FORBIDDEN", False)
except ApiError as e:
    check("empty admin -> FORBIDDEN (no invoke)", e.code == "FORBIDDEN")

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    raise SystemExit(1)
print("ALL PASS")
