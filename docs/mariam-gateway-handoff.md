# Message to Mariam — gateway integration

Author: Tishneet. Ready to send; this file is not an external message delivery.

Hi Mariam — confirmed: you own `backend.security.gateway`, privileged Lambdas,
inventory tables, audit storage and execution markers. I own workflow state and
deployment. My workflow role invokes only your six named read/authorization/
executor/audit functions in account737876441172, us-east-1, and has no permissions
on your tables, admin functions or signing secret.

My changes now support `reset_demo(control_version, control, admin)`. The service
persists a CONTROL reset fence before the gateway call and blocks new starts.
Please treat the passed CONTROL as a read-only snapshot; the gateway must not
write CONTROL. Return WarehouseState after reset, and expose the fresh run ID.
Please confirm this response contract, including how a guaranteed reset refusal
is represented. Currently any unconfirmed reset remains fenced; my recovery path
reads the current warehouse/run without invoking reset again.

Prefer `gateway.get_run_id() -> str`, unwrapping your Lambda's `{run_id: str}`.
My boundary also accepts that envelope and persists only its nonempty string.
Please import simulation via `backend.core.simulator` from repository root.
Please expose a nonfixture `gateway.name` label, such as `LAMBDA_GATEWAY`, and
retain the actual authorization `engine` field so local-policy fallback is visible.

Please reuse `from backend.ai.validation import fingerprint`. It validates and
hashes the entire PlanActions object, using json.dumps(sort_keys=True,
separators=(',', ':'), ensure_ascii=True), UTF-8 encoding and SHA-256. Action
order is significant. For this exact plan:

```json
{"actions":[{"type":"move_packages","from":"A","to":"C","count":3}]}
```

the hash is:

`4d0939f824e09200aa769aa4a7d6dd719a9c8ce70c2823e0783c34c427fe5f6a`

Elevated executor calls now receive exactly approval_id, plan_id, revision,
fingerprint, warehouse_version, run_id, decision, admin, decided_at. No task
token or internal approval fields are forwarded. Low-risk approval is null.
Guaranteed non-commit responses preserve your agreed error code and retry flag;
other responses remain unconfirmed and reconcile using the same execution ID.

Ishani owns authenticated admin identity. Coordinate signing once in her API
process; load the signing key lazily only for revoke/reset. Importing or creating
the gateway inside the workflow Lambda must never require the signing secret.

The intended setting is
`SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway`.
StateMachineArn and the physical workflow-table name are still pending deployment;
I will send the actual stack outputs afterward. No placeholder ARN is a deployed
resource. Nova Pro remains pending live validation.

Once your gateway lands, we'll test these changes on the team integration branch;
your implementation remains out of my backend contribution branch.
