# Tishneet's backend-only handoff

Author: Tishneet. Branch: `feature/ai-workflow--Tishneet`.

## Contribution boundary

This branch contains only Tishneet's backend modules, tests, requirements,
backend build tooling, scripts, and documentation. It excludes all frontend
files, Ishani's API source, Mariam's simulator/tests/PRD, and teammates' feature
commits. Rewritten commits supersede the earlier integrated history.

The old history is backed up locally in
`/tmp/sentinelos-integrated-backup-265640b.bundle`, not published as a new branch.
The existing integrated Docker project is left unchanged. This contribution's
Compose project is `sentinelos-backend`, separate from that running environment.

## Verification and later integration

`make test` runs standalone planner/persistence/setup checks against DynamoDB
Local without teammates' source. The complete workflow intentionally depends on
Mariam's simulator and Ishani's HTTP modules. Merge them later, review/apply
`docs/integration.patch`, then run `make test-integration`. Do not mistake the
standalone subset for a complete integrated workflow pass.

The integration patch preserves only three Tishneet-authored changes:

- Select WorkflowBackendOps via SENTINEL_BACKEND=workflow in Ishani's factory.
- Match exact admin groups and require a verified administrator identity.
- Postpone simulator annotations for Python3.9 host verification.

Resolve conflicting hunks with the owners if newer work supersedes them. No
permanent merge of teammates' branches is part of this branch correction.
Correction verification: 43 standalone tests passed in Docker;186 complete
backend tests passed in a separate temporary integration directory using pinned
API e4ef0cf and simulator785b26c. Those dependencies are not part of this branch.
Historical results and detailed checks are in docs/graph-execution.md.

## Retained behavior and remaining work

Planning, validation, bounded candidates, risk, approvals, durable progress,
execution reconciliation, and audit retry logic remain unchanged. Contribution
packaging, setup entry points, and documentation are corrected.
Unconfirmed execution remains EXECUTING/EXECUTION_UNCONFIRMED, blocks reset, and
uses bounded same-ID retries. A trusted operator reconciles the original plan;
there is no public execute endpoint. Audit has a separate durable cursor.

Live AWS acceptance needs account/Region/model configuration, real backend
identities, and Mariam's authorization/data/execution/audit adapter. Fixtures
remain labeled; local checks do not claim AWS deployment or real-model invocation.
