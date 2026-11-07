# SentinelOS — Tishneet's backend contribution

Author: Tishneet. Branch: `feature/ai-workflow--Tishneet`.

This branch contains Tishneet's AI planning, validation, replanning, risk,
workflow orchestration, persistence, approvals, audit delivery, AWS adapters,
backend tests, and supporting tooling/documentation. It excludes Ishani's
frontend/API and Mariam's simulator/data/security implementation. The team will
merge those contributions separately later.

## Standalone backend checks

Start Docker Desktop, then run from this repository's root:

```sh
make test
```

This builds the backend image, starts an isolated persistent DynamoDB Local,
and runs planner, intent, risk, persistence, and setup checks. No AWS credentials
or teammates' source files are required. `make down` stops these services.
`bash scripts/dev.sh up -d` starts only DynamoDB Local on this contribution branch.
No frontend is built or served. Docker's PATH adjustment is scoped to the wrapper.

## Integration after the team merge

First merge Ishani's API and Mariam's simulator into the team's integration
branch. Review/apply these small integration changes, then test:

```sh
git apply --check docs/integration.patch
git apply docs/integration.patch
make test-integration
make integration-up
```

The patch contains only Tishneet's workflow-selector, exact administrator-group
matching, and Python annotation compatibility changes. If newer teammates'
files conflict, resolve the hunks with their owners rather than overwrite files.
The integrated API runs at http://localhost:8000/v1; worker/API services use an
explicit integration profile. Ishani owns frontend startup and hosting.
After integration, `make demo` runs D1/D2/D3 through HTTP.

Fixture model/security/data adapters are labeled development fixtures, not real
Bedrock or Verified Permissions. Never deploy open local administrator access.

## AWS preparation and handoff

`make aws-build` lints/builds the Lambda artifact using an isolated Linux
ARM64/Python3.12 tooling container, without deployment. Live AWS still needs
account/model configuration and Mariam's trusted gateway.

- [Contracts and ownership](docs/contracts.md)
- [Branch scope and handoff](docs/handoff.md)
- [Verification history](docs/graph-execution.md)
- [AWS migration](docs/aws-migration.md)
