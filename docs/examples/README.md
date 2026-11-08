# Integration examples

Author: Tishneet.

`plan-status.image.live.rejected.json` and `plan-status.image.scripted.rejected.json`
are actual public WorkflowService projections read from the orchestration table
after the updated deployed worker processed each image submission. The driver
submitted via AwsWorkflowBackend directly, not Ishani's HTTP route. Both reached
REJECTED/LIMIT_EXCEEDED with real Verified Permissions and unchanged version1.
The live candidate came from Nova's image block; the scripted candidate made zero
model calls and is labeled SCRIPTED_IMAGE_FIXTURE. No image bytes are returned.
This verifies bounded image-instruction extraction plus existing authorization;
it is not a universal prompt-injection defense benchmark. The first exploratory
image probe failed strict instruction parsing; tightening the canonical output
prompt produced successful live probes. No fallback or validator relaxation was used.

`bedrock-smoke.workshop-profile.json` is the assistant-observed successful smoke
using Tishneet's default workshop AWS profile (not a bearer key), at
2026-11-08T01:31:21.142020+00:00. Two real Nova Pro calls passed; scripted snapshots
and zero inventory operations. Credentials are not included. The deployed Lambda
role was subsequently exercised by the live policy-denial probe in ../deployment.

`bedrock-smoke.nova-pro.json` preserves the successful smoke output Tishneet
pasted into the session, timestamped 2026-11-08T01:02:25.174571+00:00. It records
two real Nova Pro calls in us-east-1, with supplied scripted warehouse/failure
inputs and independent output checks. Source: user-provided terminal output;
the assistant did not independently invoke Bedrock for this result. No key is
included. This establishes bearer-key model compatibility, not deployment-role
access, real inventory integration, Verified Permissions or latency percentiles.

`plan-status.fixture.completed.json` is the complete response captured from the
existing local HTTP API for `GET /v1/plans/plan-6c6c4d33709a4c4c8578cdc784b13ea4`.
It is an actual stored response from the earlier integrated Docker environment,
not fabricated JSON. It records fixture planning/security, revision1's capacity
failure, revision2's approved alternative, and a completed commit at version3.
Its decision timestamps are historical. It contains no callback/task token.
It does not establish live Bedrock, production authentication or AWS deployment.

Ishani can diff its candidate and public approval shapes against §5.1. Internal
executor approval normalization does not change this public API representation.
