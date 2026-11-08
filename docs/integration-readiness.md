# Workflow integration readiness

Author: Tishneet. No workflow deployment claimed.

## Current checklist

- [x] Reset/revoke refusal handling and durable reset fences implemented.
- [x] Mariam gateway 756401f available in the disposable integration tree.
- [x] Approval-envelope fix e4fa706 available in her branch; remove the old expected
  failure and require approval-to-execution to pass the combined test suite.
- [x] Workflow IAM updated for six gateway callees, including sentinel-security-authorize.
- [x] INVALID_REQUEST and PLAN_VALIDATION_FAILED preserved as guaranteed no-commit
  errors, with sanitized messages and boolean retry flags.
- [x] Real Nova Pro generation and replanning smoke passed in Tishneet's terminal.
  Evidence: examples/bedrock-smoke.nova-pro.json; provided by Tishneet in chat.
- [ ] Configure AWS deployment profile and verify account737876441172/us-east-1.
- [ ] Verify deployment-role model access; bearer-key success does not prove it.
- [ ] Build combined artifact, inspect IAM/changeset and deploy workflow stack.
- [ ] Hand StateMachineArn, WorkflowTableName and WorkflowTableArn to Ishani;
  send StateMachineArn to Mariam for the reset guard.
- [ ] Complete three live reset/demo cycles plus denial, expiry, revocation and replay.

The successful model is amazon.nova-pro-v1:0 in us-east-1. The two supplied
snapshots are scripted; the model outputs are live. Generation latency was
1012.241ms; replanning latency697.707ms. Usage totals were747 and886 tokens.
These two calls do not establish a latency percentile, deployment-role access,
real warehouse integration or a deployed Step Functions workflow.

No AWS deployment credentials were available at the latest local check. No real
workflow stack outputs exist. Mariam reports Phase4 deployed with Verified
Permissions; the assistant has not independently verified her live deployment.

## Local integration boundaries

The disposable tree /tmp/sentinelos-backend-integration combines our current code,
Ishani's previously pinned API e4ef0cf and Mariam's core/data/security756401f.
Teammate implementations are not committed to Tishneet's contribution branch.
This tree is not a team integration branch or deployment and uses an older API
snapshot than Ishani's live API.

The workflow test uses fixture model responses, actual gateway/data-handler code,
moto storage, and explicitly selected LOCAL_POLICY within the mocked authorize
handler. It exercises the new Lambda transport and exact approval envelope;
it does not establish live Verified Permissions behavior. The model smoke is
separate live evidence. Public status shape was validated by Ishani against her
frontend. See ishani-workflow-deploy.md for the API runtime and permission contract.

Current combined suite:259 passed, zero expected failures; the exact approval
envelope now reaches execution. Targeted host checks:64 passed. SAM lint,
Linux ARM64/Python3.12 build and packaged gateway import/construction checks
also passed with the latest gateway. No live workflow call was made.
Historical evidence before Phase4:250 tests passed, one expected approval failure.
