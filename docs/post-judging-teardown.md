# Post-judging teardown (security condition)

The live demo runs a **demo-grade API Gateway authorizer** that grants admin to
**any** caller (`backend/api/demo_authorizer.py`). This is fine during the demo
but must not be left public. **Right after judging**, lock or remove the API so
there is no public "everyone is admin" endpoint running.

Honest statement we use everywhere (pitch / slides / submission):

> Admin actions require an authorizer's admin claim. Demo-grade here: the demo
> authorizer grants admin to any caller. Production = Cognito user pool + admin
> group, which `auth.py` already reads in prod mode.

## Do this when judging ends

One command, from the repo root, with AWS creds for account `737876441172`:

```bash
./scripts/post_judging_teardown.sh denyall      # RECOMMENDED — locks the API, reversible
```

This replaces the authorizer Lambda (`sentinelos-api-AuthorizerFunction-zDNAXNlw4mf4`)
with a deny-all version in seconds — no stack redeploy. Every route then returns
403 and the hosted UI stops working (expected). It's reversible with
`./scripts/post_judging_teardown.sh restore` if we later resume Cognito work.

Nuclear option (remove the API entirely):

```bash
./scripts/post_judging_teardown.sh delete-stack  # deletes API Gateway + Lambdas + authorizer
```

The script does nothing without an explicit mode argument, so it can't fire by
accident. Details and the exact AWS calls are in the script header.

## Scope note

The deny-all/delete only covers the **frontend-facing `sentinelos-api` stack**
(the authorizer, API Lambda, API Gateway). The `sentinel-data` and
`sentinel-workflow-tishneet` stacks are owned separately — coordinate with
Mariam/Tishneet before touching those. The benchmark claim about forged admin
requests is scoped to the data layer (per the evidence page), not this
demo-grade HTTP authorizer.
