# Deploying Mariam's data stack (`sentinel-data`, us-east-1)

Run these in the **AWS workshop VS Code environment** (where credentials work), not locally.
Nothing here deletes resources. The tables are retained even if the stack is deleted.

## 0. Before you deploy: confirm account, Region, and that nothing conflicts

```bash
git fetch && git checkout feature/security-data--Mariam && git pull
cd backend
aws sts get-caller-identity                  # note the Account number
echo "${AWS_REGION:-$AWS_DEFAULT_REGION}"    # must print us-east-1
pip install boto3 pytest 'moto[dynamodb,secretsmanager,stepfunctions]'   # if missing
python -m data.setup_tables                  # dry run: all three tables should be "missing"
aws secretsmanager describe-secret --secret-id sentinel/admin-assertion-key 2>&1 | head -1   # should say ResourceNotFound
```

**Stop if** any `sentinel_*` table or the `sentinel/admin-assertion-key` secret already exists.
CloudFormation cannot create a resource whose name is taken. Share the output first.

Optional (lets Ishani's API read the signing key without editing her template):

```bash
# Find her API function's role ARN (replace <her-stack> with her stack name)
aws cloudformation describe-stack-resource --stack-name <her-stack> \
  --logical-resource-id ApiFunctionRole --query StackResourceDetail.PhysicalResourceId --output text
# -> role name; ARN is arn:aws:iam::<account>:role/<role name>
```

## 1. Build and deploy (review the change set before confirming)

```bash
cd backend/data
sam build
sam deploy --parameter-overrides ApiFunctionRoleArn=<role ARN or leave out> StateMachineArn=<leave out until Tishneet deploys>
```

`samconfig.toml` pins stack `sentinel-data`, Region `us-east-1`, and `CAPABILITY_IAM`.
SAM shows the change set and waits for `y`.

## 2. Seed the tables (only creates missing records; never overwrites)

```bash
cd ..                               # backend/
python -m data.setup_tables --apply # tables now "matches"; prints Seed: {'warehouse': 'created', 'agent': 'created'}
```

## 3. Verify for real

```bash
aws cloudformation describe-stacks --stack-name sentinel-data --region us-east-1 \
  --query "Stacks[0].Outputs" --output table
aws lambda invoke --function-name sentinel-data-warehouse --payload '{}' \
  --cli-binary-format raw-in-base64-out --region us-east-1 /dev/stdout
aws lambda invoke --function-name sentinel-data-agent --payload '{}' \
  --cli-binary-format raw-in-base64-out --region us-east-1 /dev/stdout
aws lambda invoke --function-name sentinel-data-revoke --payload '{"admin":"admin"}' \
  --cli-binary-format raw-in-base64-out --region us-east-1 /dev/stdout   # must return FORBIDDEN
SENTINEL_AWS_TESTS=1 python -m pytest tests/test_data_aws.py -v
```

Expected: warehouse A=20/30, B=8/10, C=5/20, version 1; agent ACTIVE; revoke with a plain admin string → `FORBIDDEN`.

## 4. Hand off to Ishani

Her API stack parameters (`Backend=aws`):

| Her parameter | Value |
|---|---|
| `WarehouseFn` | output `WarehouseFnArn` |
| `AgentFn` | output `AgentFnArn` |
| `AuditFn` | output `AuditFnArn` |
| `RevokeFn` | output `RevokeFnArn` |
| `ResetFn` | output `ResetFnArn` |

**IAM her API role needs:**
- `lambda:InvokeFunction` on the five ARNs above. Her template already allows `*`; she can narrow it to these five.
- `secretsmanager:GetSecretValue` on output `AdminAssertionSecretArn`. Granted by this stack if you passed `ApiFunctionRoleArn`; otherwise she adds it to her role.

**Revoke and reset need one change in her `AwsBackendOps`.** A plain `{"admin": admin}` is refused (`FORBIDDEN`) by design. Her API must send a signed assertion, created *after* her `require_admin` succeeds:

```python
import hashlib, hmac, os, secrets, time
import boto3

_admin_key = None

def _admin_assertion(action, admin):
    """action: "REVOKE_AGENT" or "RESET_DEMO". admin must not contain '|'."""
    global _admin_key
    if _admin_key is None:
        _admin_key = boto3.client("secretsmanager").get_secret_value(
            SecretId=os.environ["ADMIN_SECRET_ARN"])["SecretString"].encode()
    issued_at, nonce = int(time.time()), secrets.token_hex(16)
    message = f"sentinel-admin-v1|{action}|{admin}|{issued_at}|{nonce}".encode()
    return {"admin": admin, "action": action, "issued_at": issued_at, "nonce": nonce,
            "signature": hmac.new(_admin_key, message, hashlib.sha256).hexdigest()}

# revoke_agent: self._invoke("REVOKE_FN", {"admin_assertion": _admin_assertion("REVOKE_AGENT", admin)})
# reset_demo:   self._invoke("RESET_FN",  {"admin_assertion": _admin_assertion("RESET_DEMO", admin)})
```

Her Lambda also needs the env var `ADMIN_SECRET_ARN` = output `AdminAssertionSecretArn`.
Assertions expire after 60 seconds and each can be used once.

## Sample requests and responses

| Lambda | Request payload | Success response |
|---|---|---|
| warehouse | `{}` | `{"warehouse_id":"demo-warehouse","version":1,"zones":{"A":{"inventory":20,"capacity":30},"B":{"inventory":8,"capacity":10},"C":{"inventory":5,"capacity":20}},"restricted_zones":["HAZMAT"]}` |
| agent | `{}` | `{"agent_id":"inventory-agent-01","status":"ACTIVE","role":"INVENTORY_MANAGER","max_transfer":10}` |
| audit | `{"plan_id":"plan-001"}` or `{}` | `{"events":[{"plan_id":"plan-001","event_id":"2026-11-07T20:00:01.000Z#a1b2c3d4","timestamp":"2026-11-07T20:00:01Z","revision":1,"event_type":"SIMULATION_FAILED","outcome":"REJECTED","reason_code":"CAPACITY_EXCEEDED","message":"..."}]}` |
| revoke | `{"admin_assertion":{...}}` | AgentRecord with `"status":"REVOKED"` |
| reset | `{"admin_assertion":{...}}` | seed WarehouseState (version 1) |

Errors (all five): `{"error":{"code":"FORBIDDEN"|"NOT_FOUND"|"INVALID_REQUEST"|"VERSION_CONFLICT"|"INTERNAL_ERROR","message":"...","retryable":false}}`.
`VERSION_CONFLICT` (retryable) means reset was refused because a plan may be running.

## Known limits

- **Reset is refused until Tishneet's state machine exists.** Redeploy with `StateMachineArn=<arn>` once it does; reset then checks for RUNNING executions (which includes plans awaiting approval).
- **Revoke/reset are refused until Ishani's API sends signed assertions** (section 4).
- Log retention uses the Lambda default (never expire). Fine for the hackathon.
