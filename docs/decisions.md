# Tishneet's development decisions

Author: Tishneet.

1. Use existing branch `feature/ai-workflow--Tishneet`, per Tishneet's latest
   instruction. Git author is Tishneet with the existing repository email.
2. Keep only Tishneet's contribution on this feature branch. Ishani's API/frontend
   and Mariam's simulator are separate integration dependencies. The previous
   integrated history is backed up locally, not retained in branch ancestry.
   Small edits to their modules are supplied as docs/integration.patch for review
   during the later team merge.
3. Docker Python3.12 is the target. DynamoDB Local uses a named persistent volume;
   the local emulator runs as root to write that fresh volume. DynamoDB has no
   exposed host port; the optional integration API uses loopback. Docker helper
   PATH is scoped to the wrapper. Project name sentinelos-backend isolates this
   setup from the previously running integrated application.
4. Fixture planning and security/data behavior are visibly labeled. They do not
   establish real Bedrock or Verified Permissions integration. AWS rejects fixture,
   in-memory, local-endpoint, and open-auth configuration.
5. Interpret a conservative supported movement grammar independently of the model.
   Unknown/ambiguous instructions require clarification. Explicit alternatives
   permission is required to redirect a destination. This is an intentional MVP
   limit, not unrestricted natural-language understanding.
6. Maximum three reserved candidates. Malformed output fails immediately; it is
   not silently repaired. No replanning after authorization denial. Every revised
   candidate passes all checks again.
7. Approval deadline is 600 seconds. Decisions bind candidate fingerprint,
   warehouse version, and run identity. Stale state fails rather than automatically
   issuing fresh approval.
8. Docker uses a local scheduler over the same business stages used by AWS.
   AWS uses Standard Step Functions; the local worker refuses AWS scheduling.
9. A worker crash during model generation ends that request after lease expiry,
   rather than issuing an unaccounted model call. Leases are 90 seconds; Bedrock
   timeout and Lambda/task deadlines are shorter.
10. Unconfirmed execution remains EXECUTING. Automatic same-identity retries back
    off and stop after five uncertain attempts. `reconciliation_required` then
    stays true and blocks reset. A trusted operator waits for the prior lease and
    calls `reconcile_execution(plan_id)`; no public executor endpoint exists.
    Execution business errors may be terminal only if they guarantee no commit.
11. Persist administrator decisions before callbacks. A decision may arrive before
    callback registration; registration must bind and deliver that same decision.
    Invalid/timed-out tokens require reconciliation, never guessed success.
12. Audit is durable with transitions and has an idempotent external delivery seam.
    A delivery outage does not undo or repeat a commit. Local UI reads canonical
    workflow evidence; AWS retries sink delivery on a schedule.
13. `decision_latency_ms` measures time to the eligible decision.
    `evaluation_ms` excludes administrator waiting time. Fixture measurements are
    not presented as real-model performance or cost. Real usage is collected from
    Bedrock when connected; no invented cost estimates.
14. The first combined suite exposed import-path/annotation compatibility issues.
    Docker testing exposed volume permissions and an inherited-endpoint test
    assumption. Independent review exposed ambiguous execution/start responses and
    callback registration races. Regression tests cover these repairs.
15. Live AWS migration still requires credentials, accessible model/Region,
    backend-enforced authentication, and Mariam's gateway. No AWS deployment,
    production reliability, or untested interactive-browser result is claimed.
