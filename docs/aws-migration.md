# AWS migration and verification

Author: Tishneet. This documents `aws.py`, `statemachine.asl.json`, and the
standalone workflow SAM template. Docker development remains the first target.

## What is supplied

* The Bedrock provider shares the local planner interface and independently
  validates returned actions. The configured model must support the selected
  Converse/tool-use behavior; model access is verified in the team's account.
* The Standard workflow dispatches one durable business transition per Lambda
  task. Every candidate is validated and authorized again. Replanning and model
  invocation do not use automatic Step Functions retries.
* Approval uses `lambda:invoke.waitForTaskToken` with a 600-second task timeout.
  The trusted registration handler stores the token; public serializers must
  exclude it. Both approve and deny send a decision callback, after which the
  workflow reads the durable status instead of trusting browser output.
* An explicit failure branch persists a generic failure reason. Completion
  already committed by the executor must not be overwritten by a transport error.
* `AwsWorkflowBackend` starts a Standard execution named by the durable plan ID.
  After an ambiguous network failure, reconcile that name/input or use
  `start_existing(plan_id)`; never create another plan as a start retry.

The AWS adapter contracts are tested with injected services/clients. Static
graph tests check reachability, context preservation, timeout and catch paths.
These checks do **not** constitute AWS service validation or deployment.

## Prerequisites owned jointly with the team

1. Confirm account, Region, credentials and actual accessible Bedrock model or
   inference profile. Supply both the profile ARN (if applicable) and the exact
   underlying foundation-model ARNs its invocation requires.
2. Finish Mariam's trusted authorization, data, simulator, audit sink, and atomic executor
   adapters. Package their agreed factory module with the workflow artifact and
   set `SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway`.
   Missing adapters must fail closed. Mariam's gateway wraps her privileged
   Lambdas; the workflow does not access her inventory/agent/audit tables or
   signing key. The template now restricts invocation to her five published gateway functions
   in account737876441172/us-east-1. Revoke/reset are API-role operations only.
3. Finish Ishani's authenticated API connection. Approvals, revocation and reset
   must receive a backend-established administrator identity. Never deploy open
   local authentication or fixture security/execution adapters.
4. Coordinate table name, module contracts, Lambda ARNs and the shared SAM editor.
   This standalone template must be reconciled with the shared deployment rather
   than deployed as a competing warehouse or API stack.

## Build and configuration

The workflow SAM template is `backend/workflows/template.yaml`. Its CodeUri is
the repository root so the `backend.workflows` package remains importable. A
custom Makefile builder assembles only backend runtime code and its pinned
dependency closure; it excludes local virtualenvs, PDFs, frontend, and tests.
Build locally with `make aws-build`, which uses the isolated Linux ARM/Python3.12
tooling image. The builder explicitly rejects other platforms/Python versions.
The in-source flag skips SAM's generic staging copy of local virtualenv symlinks;
the custom builder writes only to SAM's artifact directory. The Lambda target is
ARM64, matching the Linux ARM dependency build on this Mac.

For an isolated lint/build/import check without installing SAM on the host:

```sh
bash scripts/aws_build.sh
```
Inspect the generated changeset and IAM before a separately authorized deploy.

Run `make bedrock-smoke` after configuring temporary credentials outside Git. It
makes two real model calls against scripted snapshots, validates generation and
replanning, and performs zero inventory operations. Nova Pro is the target;
successful account/model access still needs live evidence. The model-facing tool
schema uses Nova's supported subset while the complete independent backend
validator remains authoritative. See [Nova tool definitions](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html).
Failures stop the check; fixtures never replace a failed Bedrock call.

### First live checks without Docker

From the repository root, use the existing virtual environment:

```sh
.venv/bin/python -m scripts.bedrock_smoke --prompt-key --region us-east-1 --model-id amazon.nova-pro-v1:0
```

Run this in your own interactive terminal. The key is entered with hidden input,
is never saved to a file, and exists only in that Python process. Model ID is a
target until the smoke passes. Key Region/access must match; if a permitted Nova
inference profile is required, pass its exact ID with `--model-id` and rerun.
Do not paste tokens in chat or pass them as command-line arguments.

For deployment, configure the temporary access key, secret and session token
using Workshop Studio's CLI credential instructions outside the repository, then:

```sh
.venv/bin/python -m scripts.aws_preflight --profile default
.venv/bin/python -m scripts.bedrock_smoke --profile default --region us-east-1 --model-id amazon.nova-pro-v1:0
```

Replace `default` with the configured profile name. The read-only preflight stops
for any account other than 737876441172 and targets us-east-1. Identity success
does not prove deployment permissions. The profile model test explicitly ignores
an inherited Bedrock bearer key, so it checks the profile's model permissions.
The deployed Lambda uses IAM role credentials, not a personal bearer token.
Build/deploy and the live workflow acceptance gate follow only after access is
verified; no stack outputs can be supplied before a successful deployment.

Required runtime configuration:

| Variable | Purpose |
|---|---|
| `SENTINEL_RUNTIME=aws` | Disable local scheduling for AWS-managed requests |
| `SENTINEL_MODEL_PROVIDER=bedrock` | Require the real model provider |
| `BEDROCK_MODEL_ID` | Accessible model/profile selected by the team |
| `SENTINEL_WORKFLOW_TABLE` | Durable orchestration records |
| `SENTINEL_TRUSTED_ADAPTER_MODULE` | Packaged trusted adapter factory |
| `SENTINEL_APPROVAL_TIMEOUT=600` | Backend deadline, aligned with ASL |
| `SENTINEL_STATE_MACHINE_ARN` | Trusted API wrapper only, from stack output |

The workflow Lambda intentionally does not reference the state-machine ARN in
its environment: that would create a CloudFormation dependency cycle. The API
runtime needs `states:StartExecution` scoped to the output ARN. The workflow role
is limited to its own table, specified model resources and trusted Lambda ARNs;
`states:SendTaskSuccess` requires `Resource: '*'` because task-token callbacks
do not support resource-level scoping. See the [Step Functions authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_stepfunctions.html).
Do not grant browser identities that role.

The generic store's prefix listing is suitable for a bounded hackathon dataset.
Replace scan-based discovery with keyed/indexed queries before production scale;
the AWS stack intentionally makes no production throughput claim.
Transactional document puts use the underlying `dynamodb:PutItem` permission,
as specified in [DynamoDB transaction IAM documentation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html).

Workflow events persist with transitions. A separate per-plan AUDIT_CURSOR avoids
collisions with workflow leases. `gateway.append_audit(event)` must deduplicate
event identities; the schedule retries outstanding delivery once per minute.
An audit outage never repeats inventory execution. This is bounded demo queue
discovery; replace scans before increasing scale.

## Callback and failure recovery

Persist a decision before sending its task token, then mark delivery only after
success. An interrupted callback delivery is retried using the same stored
decision and token. Invalid/expired token errors are not proof of execution:
inspect durable plan state and Step Functions history. A callback never skips
reauthorization, resimulation or the executor's authoritative conditional commit.

An interrupted model invocation is a safe failure, not an invitation to generate
another hidden candidate. An interrupted execution is reconciled through Mariam's
idempotent execution result before any retry. Backend dependency errors and
CloudWatch logs must not expose model credentials or callback tokens.

## Live acceptance gate (not run by fixture tests)

After deploying a known commit, record the Region, stack outputs and model ID.
Run D1/D2/D3 with exact counts and versions, then repeat for denial, expiry,
duplicate approval, revocation while pending, warehouse conflict, Lambda failure,
authorization outage, and old-plan replay after reset. Check DynamoDB evidence and
Step Functions execution history. Run three complete reset/walkthrough cycles.
Measure model calls, token usage and decision latency separately from human wait.

Official references: [Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html),
[Lambda callback integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html),
[Standard StartExecution idempotency](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html).
