# Message to Mariam — published gateway integration

Author: Tishneet. Draft only; not sent externally.

Hi Mariam — I fetched your published gateway at a4b262f and tested it in a
disposable integration tree. Root import, lazy signing-key construction, routine
workflow execution and guaranteed reset refusal pass locally. My CONTROL fence
now clears only for an agreed exact no_commit=True reset refusal. Unknown
outcomes remain fenced and reconcile without repeating reset.

One blocker needs your change in backend/data/executor.py::_check_approval:
our agreed outbound envelope is:

```text
approval_id, plan_id, revision, fingerprint, warehouse_version,
run_id, decision, admin, decided_at
```

Your gateway correctly forwards it unchanged, but the published executor checks
approval.status, so approved elevated plans return APPROVAL_INVALID. Please
check decision == APPROVED, match plan_id to the execute request as well as
revision/fingerprint/warehouse_version/run_id, and require the verified admin and
decision timestamp. Keep idempotent replay of an already committed revision
returning its original result. Please add tests using this exact envelope,
including denied decision, wrong plan ID and missing identity/timestamp.

Fingerprint reuse matches backend.ai.validation.fingerprint. Workflow IAM now
invokes only the five functions your gateway uses: sentinel-data-{warehouse,
agent,runid,execute,audit-append}. No inventory-table, admin-function or signing-key
permissions. LOCAL_POLICY remains visible; I am not claiming Verified Permissions
is enabled.

StateMachineArn is still pending AWS credentials and deployment. I will send the
actual output for your reset Lambda's STATE_MACHINE_ARN; no resource is deployed
yet. You do not need to push the gateway again—it is now available on your branch.
