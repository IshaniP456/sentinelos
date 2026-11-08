# Deployed workflow handoff

Author: Tishneet. Account737876441172, us-east-1.

Subsequent image-input update: worker code05cb885 deployed successfully, with
ImageDemoEnabled=true. See image-worker-update.json, image-demo-results.json and
../image-input-contract.md. Real and scripted image requests passed live denial
acceptance; original table/state-machine identifiers and permissions are unchanged.
Ishani's image HTTP routing and UI remain separate integration work. The original
source/deployment manifests below describe the initial warehouse deployment.

Stack `sentinel-workflow-tishneet` reached CREATE_COMPLETE. Actual resource
identifiers are in stack-outputs.json. The deployment packages Tishneet commit
d6c0aee with Mariam's security/core gateway commit756401f. No API, frontend,
data-handler implementation, credentials or tests were included in the Lambda.
Source and deployment manifests bind the exact files, archive and changeset.
The deployed Lambda code hash matches the reviewed ZIP artifact.

## For Ishani

- Consume api-env.json as environment additions to your existing API settings;
  retain your ADMIN_SECRET_ARN, verified auth and other existing configuration.
- Add api-policy.json to the API role while retaining existing logging/signing
  permissions. This is a supplementary policy, not a replacement for the role.
- Remove DYNAMODB_ENDPOINT_URL. No developer AWS profile or bearer key belongs
  in the API Lambda environment. Role-based credentials are used in AWS.
- Package the combined workflows/ai/security/core dependencies with your API.
  Our contribution branch deliberately does not vendor teammate sources.
- WorkflowBackendOps handles submission/status/callbacks in the API process;
  the separate deployed workflow Lambda does the planning/authorization/execution.
  SendTaskSuccess handles both approval and denial; SendTaskFailure is not used.
- See ../ishani-workflow-deploy.md for runtime boundaries and IAM explanations.

## For Mariam

Use StateMachineArn from stack-outputs.json for the reset Lambda's
STATE_MACHINE_ARN, then redeploy that guard before reset-based joint walkthroughs.
The workflow role invokes all six agreed functions, including
sentinel-security-authorize, without inventory-table or secret access.

## Acceptance evidence and remaining work

The live policy-denial probe used the deployed Step Functions state machine and
Lambda role, real Nova Pro and live Verified Permissions. It submitted an
11-package plan. Result: REJECTED / LIMIT_EXCEEDED, engine VERIFIED_PERMISSIONS,
warehouse version1 unchanged, no execution result. Step Functions FAILED with
PlanRejected is the expected transport outcome for that policy denial.
See live-policy-denial.json. This is not an approve-to-execute acceptance result.

Remaining: Ishani's API switch, Mariam's reset-guard wiring, then live normal
execution, capacity replanning, approval/denial/timeout, revocation, replay and
three controlled reset/walkthrough cycles. No messages were sent externally by
the assistant, and neither teammate's deployed API/reset configuration was changed.

The stack includes a once-per-minute audit delivery schedule, pay-per-request
DynamoDB with PITR, and Standard Step Functions. AWS usage charges apply until
resources are removed; retain the orchestration table/evidence for the demo.
