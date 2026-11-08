# Message to Mariam — Phase4 integration update

Author: Tishneet. Draft only; the assistant has not sent this message.

Hi Mariam — I fetched756401f, including approval fix e4fa706. My workflow IAM
now includes sentinel-security-authorize alongside the five data functions, with
no inventory-table, admin-function, signing-secret or direct Verified Permissions
permissions. INVALID_REQUEST and PLAN_VALIDATION_FAILED are now preserved as
sanitized guaranteed no-commit errors, including the boolean retry flag.

The combined local suite now passes259 tests with no expected approval failure.
The real workflow calls your published gateway/data handlers against moto;
this test explicitly selects LOCAL_POLICY inside the mocked authorize handler,
so it is not a claim that I independently verified your live Cedar deployment.
The exact decision/decided_at/plan_id approval envelope now reaches execution.

Tishneet's live Bedrock smoke passed with amazon.nova-pro-v1:0 in us-east-1:
two real calls, generation and replanning checks passed, zero inventory writes.
Workflow stack is now CREATE_COMPLETE; the live denial probe reached Verified
Permissions and left warehouse version1 unchanged. Please set your reset Lambda
STATE_MACHINE_ARN to:

arn:aws:states:us-east-1:737876441172:stateMachine:WorkflowStateMachine-xOljcGvrjU3e

Then redeploy the reset guard before the joint reset/demo run. Actual outputs
and evidence are recorded in docs/deployment/.
