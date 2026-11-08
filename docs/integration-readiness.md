# Workflow integration readiness

Author: Tishneet. Local checks recorded 2026-11-07; no live deployment claimed.

## Checklist and execution order

- [x] Implement Mariam's reset/revoke refusal classification and sanitized errors.
- [x] Fetch published gateway a4b262f into a disposable integration tree; leave
  teammate implementations out of Tishneet's contribution branch.
- [x] Check fingerprint reuse, lazy signing and routine execution with real gateway
  code and mocked AWS data handlers.
- [ ] Mariam: align executor approval with `decision` envelope. Published executor
  reads `status`, producing APPROVAL_INVALID. The integration regression is an
  explicit expected failure until the owner fixes it; it is not acceptance.
- [ ] Configure temporary Workshop Studio credentials locally, outside Git/chat.
- [ ] Run `make bedrock-smoke`: two real Converse calls, zero inventory operations,
  generation and replan validated independently. Target `amazon.nova-pro-v1:0`,
  us-east-1; record the successful actual model ID or permitted inference profile.
- [ ] Build the combined team artifact, inspect changeset/IAM, deploy workflow
  stack and record StateMachineArn plus WorkflowTableName.
- [ ] Hand outputs to Ishani and Mariam, then verify live submit/replan/approve/
  execute, denial, reset, expiry and replay. Fixtures never substitute for Bedrock.

AWS credentials were not configured at this check. No stack ARN/table output or
successful live Nova result exists. The model name above is a target, not evidence
of account access. If it needs an inference profile, validate that profile before
choosing its exact IAM resources.

## Local evidence

The disposable tree `/tmp/sentinelos-backend-integration` combines Tishneet's
working files, Ishani's previously pinned API e4ef0cf and Mariam's published
core/data/security a4b262f. It is not a team integration branch or a deployment.
The API snapshot is older than Ishani's live API, so these tests do not verify her
latest deployed API. Model responses are fixtures in this suite; AWS handlers
use moto. Standalone backend tests use DynamoDB Local.

Recorded results: 73 standalone backend tests passed before the IAM reduction;
the final combined run passed 250 tests with one explicit expected failure for
the approval mismatch. That combined run includes the updated five-function IAM
checks. SAM lint and Linux ARM64/Python3.12 build passed; the packaged team gateway
imported and constructed with boto3.client blocked and no signing key loaded.
These are local checks, not AWS deployments or live service tests.

`test_published_gateway.py` runs the actual workflow into Mariam's real gateway
and data handlers. Routine execution changes (20,8,5,v1) to (17,8,8,v2).
Replanning reaches approval revision2; the subsequent executor contract mismatch
is deliberately reported as an expected failure and blocks live acceptance.

## Message to Ishani

Thanks—the frontend validation closes the response-shape check. Confirmed
`SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway`; Mariam's module is now
published at a4b262f. Our local integration found one blocker for her: the executor
reads approval.status while the agreed outbound record uses decision. I've
prepared the exact owner change and regression test.

StateMachineArn and SENTINEL_WORKFLOW_TABLE are still pending deployment. Nova Pro
is the agreed target, but live validation has not run; no fixture fallback will
be enabled. I'll send actual stack outputs and the validated model/profile ID
before your Backend=workflow redeploy. No changes to backend/api/ are included.

These are drafts only; no external messages have been sent.
