"""HTTP response helpers — API Gateway proxy format + contract shapes.

Every handler returns a dict shaped like an API Gateway Lambda-proxy response:
``{"statusCode": int, "headers": {...}, "body": "<json string>"}``.

CORS: the React client calls with ``credentials: 'include'`` (admin session
cookie), so the browser forbids a wildcard origin. We therefore echo a single
configured origin and set ``Access-Control-Allow-Credentials: true``
(contract §0 / NFR01 — no secrets in the browser, auth stays server-side).
"""

import json
import os

# A specific origin is required when credentials are included — never "*".
CORS_ORIGIN = os.environ.get("SENTINEL_CORS_ORIGIN", "http://localhost:5173")


def _base_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": CORS_ORIGIN,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": "Content-Type, X-Admin-Token",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    }


def ok(body, status=200):
    """A successful JSON response."""
    return {
        "statusCode": status,
        "headers": _base_headers(),
        "body": json.dumps(body),
    }


def error(code, message, status, retryable=False):
    """The standard error object (contract §3.6)."""
    return {
        "statusCode": status,
        "headers": _base_headers(),
        "body": json.dumps(
            {"error": {"code": code, "message": message, "retryable": retryable}}
        ),
    }


def preflight():
    """Response to a CORS preflight (OPTIONS) request."""
    return {"statusCode": 204, "headers": _base_headers(), "body": ""}


# Map common backend error codes to sensible HTTP statuses (contract §3.6).
STATUS_FOR_CODE = {
    "INVALID_REQUEST": 400,
    "PLAN_VALIDATION_FAILED": 422,
    "AUTHORIZATION_DENIED": 403,
    "SIMULATION_FAILED": 422,
    "MAX_ATTEMPTS_REACHED": 409,
    "APPROVAL_REQUIRED": 409,
    "APPROVAL_DENIED": 409,
    "APPROVAL_EXPIRED": 410,
    "VERSION_CONFLICT": 409,
    "ALREADY_EXECUTED": 409,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "MODEL_ERROR": 502,
    "INTERNAL_ERROR": 500,
}

# Codes that are safe for the client to retry.
RETRYABLE_CODES = {"VERSION_CONFLICT", "MODEL_ERROR", "INTERNAL_ERROR"}


class ApiError(Exception):
    """Raised by handlers / backend ops to produce a standard error response."""

    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_FOR_CODE.get(code, 400)
        self.retryable = code in RETRYABLE_CODES

    def to_response(self):
        return error(self.code, self.message, self.status, self.retryable)
