"""The seven frontend-facing endpoints (contract §5), as one Lambda.

The timeline permits several endpoints to share one Lambda handler. ``handler``
is the single API Gateway (proxy) entry point; it routes by method + resource
path to the per-endpoint functions below. Each per-endpoint function is also
importable on its own if you later split them into separate Lambdas.

Routing:
  POST   /v1/plans                      -> submit_plan            202
  GET    /v1/plans/{plan_id}            -> get_plan               200
  GET    /v1/warehouse                  -> get_warehouse          200
  GET    /v1/agents/current            -> get_agent              200
  GET    /v1/audit?plan_id=...          -> get_audit              200
  POST   /v1/approvals/{approval_id}    -> decide_approval  [admin]202
  POST   /v1/agents/current/revoke      -> revoke_agent     [admin]200
  POST   /v1/demo/reset                 -> reset_demo       [admin]200
"""

import json

try:  # package context (local: python -m backend.api.*)
    from .auth import require_admin
    from .backend_ops import get_backend
    from .responses import ApiError, ok, preflight, error
except ImportError:  # flat context (deployed Lambda, CodeUri=backend/api)
    from auth import require_admin
    from backend_ops import get_backend
    from responses import ApiError, ok, preflight, error


def _body(event):
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise ApiError("INVALID_REQUEST", "Request body must be valid JSON.")


# --- per-endpoint handlers --------------------------------------------------

def submit_plan(event):
    # Exactly one input variant — text OR image, never mixed (image contract).
    # Text: {instruction}. Image: {image_b64, mime_type, demo_mode?}.
    body = _body(event)
    keys = set(body.keys())
    has_text = "instruction" in keys
    has_image = "image_b64" in keys

    if has_text and has_image:
        raise ApiError("INVALID_REQUEST", "Provide either 'instruction' or an image, not both.")

    if has_image:
        extra = keys - {"image_b64", "mime_type", "demo_mode"}
        if extra:
            raise ApiError("INVALID_REQUEST", f"Unexpected field(s): {', '.join(sorted(extra))}.")
        image_b64 = body.get("image_b64")
        mime = body.get("mime_type")
        if not isinstance(image_b64, str) or not image_b64:
            raise ApiError("INVALID_REQUEST", "Field 'image_b64' (base64 string) is required.")
        if mime not in ("image/png", "image/jpeg"):
            raise ApiError("INVALID_REQUEST", "mime_type must be image/png or image/jpeg.")
        # Browser never holds model creds; backend decodes + runs the model.
        return ok(get_backend().start_image_plan(image_b64, mime, body.get("demo_mode")), status=202)

    # Text plan (contract §2.4): browser submits only the instruction.
    extra = keys - {"instruction"}
    if extra:
        raise ApiError("INVALID_REQUEST", f"Unexpected field(s): {', '.join(sorted(extra))}.")
    instruction = body.get("instruction")
    if not isinstance(instruction, str):
        raise ApiError("INVALID_REQUEST", "Field 'instruction' (string) is required.")
    return ok(get_backend().start_plan(instruction), status=202)


def get_plan(event):
    plan_id = (event.get("pathParameters") or {}).get("plan_id")
    if not plan_id:
        raise ApiError("INVALID_REQUEST", "Missing plan_id.")
    return ok(get_backend().get_plan_status(plan_id))


def get_warehouse(event):
    return ok(get_backend().get_warehouse())


def get_agent(event):
    return ok(get_backend().get_agent())


def get_audit(event):
    plan_id = (event.get("queryStringParameters") or {}).get("plan_id")
    return ok(get_backend().get_audit(plan_id))


def decide_approval(event):
    admin = require_admin(event)  # admin-only (NFR01)
    approval_id = (event.get("pathParameters") or {}).get("approval_id")
    if not approval_id:
        raise ApiError("INVALID_REQUEST", "Missing approval_id.")
    decision = _body(event).get("decision")
    return ok(get_backend().record_approval(approval_id, decision, admin), status=202)


def revoke_agent(event):
    admin = require_admin(event)  # admin-only
    return ok(get_backend().revoke_agent(admin))


def reset_demo(event):
    admin = require_admin(event)  # admin-only
    return ok(get_backend().reset_demo(admin))


# --- router / single Lambda entry point -------------------------------------

def _match(method, path):
    """Return a handler fn for (method, path), or None. Path has /v1 stripped."""
    parts = [p for p in path.split("/") if p]
    if method == "POST" and parts == ["plans"]:
        return submit_plan
    if method == "GET" and len(parts) == 2 and parts[0] == "plans":
        return lambda e: get_plan(_with_path(e, {"plan_id": parts[1]}))
    if method == "GET" and parts == ["warehouse"]:
        return get_warehouse
    if method == "GET" and parts == ["agents", "current"]:
        return get_agent
    if method == "GET" and parts == ["audit"]:
        return get_audit
    if method == "POST" and len(parts) == 2 and parts[0] == "approvals":
        return lambda e: decide_approval(_with_path(e, {"approval_id": parts[1]}))
    if method == "POST" and parts == ["agents", "current", "revoke"]:
        return revoke_agent
    if method == "POST" and parts == ["demo", "reset"]:
        return reset_demo
    return None


def _with_path(event, params):
    merged = dict(event.get("pathParameters") or {})
    merged.update(params)
    e = dict(event)
    e["pathParameters"] = merged
    return e


def handler(event, context=None):
    """API Gateway proxy entry point."""
    method = (event.get("httpMethod") or event.get("requestContext", {})
              .get("http", {}).get("method") or "GET").upper()
    path = event.get("path") or event.get("rawPath") or "/"

    if method == "OPTIONS":
        return preflight()

    # Accept paths with or without the /v1 stage prefix.
    norm = path
    if norm.startswith("/v1"):
        norm = norm[len("/v1"):] or "/"

    fn = _match(method, norm)
    if fn is None:
        return error("NOT_FOUND", f"No route for {method} {path}", 404)

    try:
        return fn(event)
    except ApiError as e:
        return e.to_response()
    except Exception as e:  # fail closed; never leak internals (NFR04)
        return error("INTERNAL_ERROR", "Unexpected server error.", 500, retryable=True)
