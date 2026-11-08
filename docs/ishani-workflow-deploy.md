# Ishani: workflow deployment handoff

Author: Tishneet. Workflow deployed; actual values and supplementary API policy
are in deployment/api-env.json, api-policy.json and stack-outputs.json. This
document is a draft handoff, not a sent message.

## Runtime split

WorkflowBackendOps runs inside the API Lambda for submission, status, decision
persistence, callbacks, warehouse/agent reads and admin operations. Heavy planning,
authorization, simulation and execution are advanced by a separate workflow Lambda,
scheduled by Standard Step Functions. The API must not call tick or flush_audit.
It needs table and callback access as well as StartExecution; it does not need
permission to invoke the workflow Lambda, executor, authorize or audit-append.
No Bedrock invocation occurs in API handlers, although the shared factory requires
the Bedrock provider/model configuration when constructing the service.

## API environment

```text
SENTINEL_BACKEND=workflow
SENTINEL_RUNTIME=aws
SENTINEL_STORE=dynamodb
SENTINEL_STATE_MACHINE_ARN=arn:aws:states:us-east-1:737876441172:stateMachine:WorkflowStateMachine-xOljcGvrjU3e
SENTINEL_WORKFLOW_TABLE=sentinel-workflow-tishneet-WorkflowTable-INY7ZA3DJ03A
SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway
SENTINEL_APPROVAL_TIMEOUT=600
SENTINEL_MODEL_PROVIDER=bedrock
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
SENTINEL_AUTH_MODE=prod
ADMIN_SECRET_ARN=<existing Mariam signing-secret ARN>
```

Use us-east-1. Remove DYNAMODB_ENDPOINT_URL in AWS. Preserve existing verified
admin authentication/signing settings. No bearer token, static AWS credentials or
developer profile belongs in Lambda environment variables; Lambda uses its role.
Package the agreed backend workflows/ai/security/core dependencies with the API.
The model ID passed both the bearer-key and workshop-profile smoke. The deployed
Lambda role also generated the policy-denied plan successfully.

## API IAM

Keep existing logging and signing-secret access. Add these scoped permissions:

| Actions | Resource |
|---|---|
| states:StartExecution | Actual StateMachineArn output |
| states:SendTaskSuccess | `*` (task-token action has no resource-level scoping) |
| dynamodb:GetItem, dynamodb:PutItem, dynamodb:Scan | Actual WorkflowTableArn output |
| lambda:InvokeFunction | The five exact ARNs below |

```text
arn:aws:lambda:us-east-1:737876441172:function:sentinel-data-warehouse
arn:aws:lambda:us-east-1:737876441172:function:sentinel-data-agent
arn:aws:lambda:us-east-1:737876441172:function:sentinel-data-runid
arn:aws:lambda:us-east-1:737876441172:function:sentinel-data-revoke
arn:aws:lambda:us-east-1:737876441172:function:sentinel-data-reset
```

Both approval and denial use SendTaskSuccess after persisting the decision;
SendTaskFailure is not used. No direct access to Mariam's inventory tables is
required. API role signing access remains secretsmanager:GetSecretValue on her
existing exact secret ARN (and her existing key policy, if applicable).
Workflow store transactions contain Put operations; underlying PutItem permission
covers those transactional writes. There are no Update/Delete/ConditionCheck
operations in this store. This is not a request for dynamodb:* permissions.

## Deployment and joint acceptance

Our stack exposes StateMachineArn, WorkflowTableName and WorkflowTableArn. Start
contract is name=plan_id, input={plan_id}; instruction is already persisted.
Mariam's executor approval fix is published at e4fa706 and included in756401f;
confirm her live executor includes it before the joint elevated-plan test.
Mariam reports the756401f Verified Permissions deployment is live.

Send the state-machine ARN to Mariam and wait for reset-guard wiring before using
reset in the live walkthrough. Then flip Backend=workflow and verify submission,
replanning, approval/denial, timeout and one-time execution. Keep task tokens
server-side. The workflow stack is deployed; use the actual outputs in deployment/.

References: [DynamoDB transactional IAM](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html),
[Step Functions actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_stepfunctions.html).
