"""Admin authentication for mutating admin routes (contract §5, §7; NFR01).

The approval, revocation, and reset endpoints must be restricted to an
authenticated administrator — distinct from the inventory-agent identity and
from an ordinary operator. The *final* mechanism is a kickoff decision with
Mariam; this module keeps that decision in one pluggable place.

IMPORTANT: there is NO shared admin secret in the frontend. The browser never
holds a credential that grants admin authority. The two supported modes:

* ``prod`` (default): an API Gateway authorizer (e.g. Cognito user-pool or a
  Lambda authorizer) authenticates the caller and populates
  ``event.requestContext.authorizer``. We require an ``admin`` claim/group.
  The browser just sends its session cookie; the token never reaches JS.

* ``dev``: for local testing only. A server-side token
  (``SENTINEL_ADMIN_TOKEN``) must be presented in the ``X-Admin-Token``
  header. This is a stand-in for the real authorizer so the flow is testable
  before auth infra exists — it is never used in the judged deployment.

* ``open``: for local browser UI testing ONLY — treats every caller as admin
  so the dashboard can exercise approve/revoke/reset without auth infra (the
  browser sends a cookie, not a header). MUST NOT be used in any deployment.
"""

import json
import os

try:  # package (local) vs flat (deployed Lambda)
    from .responses import ApiError
except ImportError:
    from responses import ApiError

AUTH_MODE = os.environ.get("SENTINEL_AUTH_MODE", "prod")


def _header(event, name):
    headers = event.get("headers") or {}
    # Header names are case-insensitive.
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


def require_admin(event):
    """Return the admin identity string, or raise ApiError(FORBIDDEN).

    The returned identity is recorded on approval/revocation events so the
    audit log can show who decided (contract §5.2, PRD FR07/FR12).
    """
    if AUTH_MODE == "open":
        # Local UI testing only — NEVER deployed. Every caller is admin.
        return os.environ.get("SENTINEL_ADMIN_ID", "admin-open")

    if AUTH_MODE == "dev":
        expected = os.environ.get("SENTINEL_ADMIN_TOKEN")
        provided = _header(event, "X-Admin-Token")
        if not expected:
            raise ApiError(
                "INTERNAL_ERROR",
                "Admin auth not configured (SENTINEL_ADMIN_TOKEN unset).",
                status=500,
            )
        if provided != expected:
            raise ApiError("FORBIDDEN", "Administrator authorization required.")
        return os.environ.get("SENTINEL_ADMIN_ID", "admin-local")

    # prod: trust only claims the API Gateway authorizer established.
    # (Hardening reconciled from Tishneet's integration.patch — exact group
    # membership, HTTP-API JWT claim shape, and a required verified identity.
    # This identity is what AwsBackendOps signs into Mariam's admin assertion,
    # so it MUST be a real non-empty string, never a literal fallback.)
    ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    # REST (claims), HTTP API (jwt.claims), or Lambda-authorizer (lambda) shapes.
    claims = (ctx.get("jwt") or {}).get("claims") or ctx.get("claims") or ctx.get("lambda") or ctx

    groups = set()
    for key in ("cognito:groups", "groups"):
        value = claims.get(key, [])
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                parsed = value.replace(" ", ",").split(",")
            value = parsed if isinstance(parsed, list) else [parsed]
        if isinstance(value, list):
            groups.update(g.strip().lower() for g in value if isinstance(g, str))

    role = claims.get("role") or claims.get("custom:role")
    if "admin" not in groups and role != "admin":
        raise ApiError("FORBIDDEN", "Administrator authorization required.")

    identity = claims.get("email") or claims.get("sub")
    if not isinstance(identity, str) or not identity.strip():
        raise ApiError("FORBIDDEN", "Verified administrator identity required.")
    return identity
