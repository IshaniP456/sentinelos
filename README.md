# SentinelOS

AI warehouse agent with security guardrails (AWS × A10 Hackathon).
Backend integration documentation: Tishneet.

This checkout combines Ishani's frontend/API with Tishneet's AI planning,
validation, replanning, workflow orchestration, persistence, approvals, audit
delivery, AWS adapters, tests and deployment evidence. Mariam's simulator,
data and security implementation remains a separate integration dependency.
Frontend/API setup is documented in frontend/README.md and backend/api/README.md.

## Standalone backend checks

Start Docker Desktop, then run from this repository's root:

```sh
make test
```

This builds the backend image, starts an isolated persistent DynamoDB Local,
and runs planner, intent, risk, persistence, and setup checks. No AWS credentials
or teammates' source files are required. `make down` stops these services.
`bash scripts/dev.sh up -d` starts only DynamoDB Local on this contribution branch.
The backend Compose setup does not serve the frontend. Docker's PATH adjustment
is scoped to the wrapper; Ishani's frontend has its own setup instructions.

## Integration after the team merge

Mariam's simulator/security contribution must also be merged before running the
complete workflow suite. Ishani's API already selects workflow mode and includes
her auth reconciliation. Review docs/integration.patch with the owners only for
any remaining applicable changes; do not blindly apply already-adopted hunks.
Then test:

```sh
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
ARM64/Python3.12 tooling container, without deployment. The workflow stack is
already deployed with Mariam's separately packaged gateway; actual outputs,
API environment/IAM additions and live test evidence are in docs/deployment.
Source merges do not automatically redeploy the API or workflow.

- [Contracts and ownership](docs/contracts.md)
- [Branch scope and handoff](docs/handoff.md)
- [Verification history](docs/graph-execution.md)
- [AWS migration](docs/aws-migration.md)
