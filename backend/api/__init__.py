"""SentinelOS frontend-facing HTTP API (Ishani owns; contract §5).

These are the trusted HTTP entry points that connect the React dashboard to
the backend AWS services. This package owns request parsing, admin
authentication, CORS, and contract-shaped responses — it does NOT implement
core authorization or execution logic. Those live behind the BackendOps seam
(see backend_ops.py) and are implemented by Mariam (security/data/execution)
and Tishneet (planning workflow / Step Functions).
"""
