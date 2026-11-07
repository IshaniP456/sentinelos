"""Signed administrator assertions for revoke and reset (PRD NFR01, contract section 7).

Ishani's API authenticates the administrator. Mariam's Lambdas cannot see that
check, and a plain ``"admin": "alice"`` string in the event proves nothing:
anyone allowed to invoke the Lambda could send it. So the API signs a short-
lived assertion with a key stored in AWS Secrets Manager, and the Lambda
verifies it.

Assertion (sent by the API as ``event["admin_assertion"]``)::

    {"admin": "alice@scu.edu", "action": "REVOKE_AGENT",
     "issued_at": 1762548000, "nonce": "<32 hex chars>",
     "signature": "<hex HMAC-SHA256>"}

    signature = HMAC_SHA256(key, "sentinel-admin-v1|<action>|<admin>|<issued_at>|<nonce>")

Rules: the action must match the Lambda, the assertion must be at most
``MAX_AGE_SECONDS`` old (and not from the future beyond small clock skew),
and each nonce can be used once (enforced by the caller via the audit log).
Any missing or malformed piece fails closed.
"""

import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from typing import Any

ACTIONS = frozenset({"REVOKE_AGENT", "RESET_DEMO"})
MAX_AGE_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 5
NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FIELDS = frozenset({"admin", "action", "issued_at", "nonce", "signature"})
MIN_KEY_BYTES = 32


class AssertionInvalid(Exception):
    """The admin assertion is missing, malformed, expired, or wrongly signed."""


def signing_message(action: str, admin: str, issued_at: int, nonce: str) -> bytes:
    """The exact bytes that are signed."""
    return f"sentinel-admin-v1|{action}|{admin}|{issued_at}|{nonce}".encode()


def sign(key: bytes, action: str, admin: str, issued_at: int, nonce: str) -> str:
    """Produce the hex signature. The API side uses this (or an identical copy)."""
    return hmac.new(key, signing_message(action, admin, issued_at, nonce), hashlib.sha256).hexdigest()


def verify(
    assertion: Any, *, key: bytes, expected_action: str, now: float | None = None
) -> dict[str, Any]:
    """Validate an assertion and return ``{"admin", "action", "issued_at", "nonce"}``.

    Raises:
        AssertionInvalid: for any problem. The message is safe to log, not to
            return to clients verbatim.
    """
    if expected_action not in ACTIONS:
        raise AssertionInvalid("Unknown protected action.")
    if not isinstance(key, bytes) or len(key) < MIN_KEY_BYTES:
        raise AssertionInvalid("Signing key is not configured.")
    if not isinstance(assertion, Mapping):
        raise AssertionInvalid("Missing admin assertion.")
    if set(assertion) != FIELDS:
        raise AssertionInvalid("Admin assertion has missing or extra fields.")

    admin, action = assertion["admin"], assertion["action"]
    issued_at, nonce, signature = assertion["issued_at"], assertion["nonce"], assertion["signature"]
    if not isinstance(admin, str) or not admin.strip() or "|" in admin or len(admin) > 256:
        raise AssertionInvalid("Invalid admin identity.")
    if action != expected_action:
        raise AssertionInvalid("Assertion was issued for a different action.")
    if type(issued_at) is not int:
        raise AssertionInvalid("issued_at must be an integer timestamp.")
    if not isinstance(nonce, str) or not NONCE_PATTERN.match(nonce):
        raise AssertionInvalid("Invalid nonce.")
    if not isinstance(signature, str) or not SIGNATURE_PATTERN.match(signature):
        raise AssertionInvalid("Invalid signature format.")

    current = time.time() if now is None else now
    if issued_at > current + MAX_CLOCK_SKEW_SECONDS:
        raise AssertionInvalid("Assertion is from the future.")
    if current - issued_at > MAX_AGE_SECONDS:
        raise AssertionInvalid("Assertion has expired.")

    expected = sign(key, action, admin, issued_at, nonce)
    if not hmac.compare_digest(expected, signature):
        raise AssertionInvalid("Signature does not match.")
    return {"admin": admin, "action": action, "issued_at": issued_at, "nonce": nonce}
