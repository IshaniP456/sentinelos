# Integration examples

Author: Tishneet.

`plan-status.fixture.completed.json` is the complete response captured from the
existing local HTTP API for `GET /v1/plans/plan-6c6c4d33709a4c4c8578cdc784b13ea4`.
It is an actual stored response from the earlier integrated Docker environment,
not fabricated JSON. It records fixture planning/security, revision1's capacity
failure, revision2's approved alternative, and a completed commit at version3.
Its decision timestamps are historical. It contains no callback/task token.
It does not establish live Bedrock, production authentication or AWS deployment.

Ishani can diff its candidate and public approval shapes against §5.1. Internal
executor approval normalization does not change this public API representation.
