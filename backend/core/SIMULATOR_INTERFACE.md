# simulate_plan — interface for the workflow

Owner: Mariam · Consumer: Tishneet (Step Functions / replanning) · Follows Team Integration Contract v1.0, §2.1, §2.3, §3.3.

## Call

```python
from core.simulator import simulate_plan

result = simulate_plan(plan, warehouse_state)
```

Pure function: no AWS calls, no DynamoDB, never modifies `plan` or `warehouse_state`. Same input always gives the same output. Malformed input never raises; it returns `passed: false`.

## Inputs

`plan` is **PlanActions only** (contract §2.3), i.e. `candidate["plan"]`, not the PlanCandidate envelope:

```json
{"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 5}]}
```

- 1–10 actions; each has exactly `type`, `from`, `to`, `count`.
- Any extra field (on the plan or an action) is rejected as `INVALID_PLAN` / `INVALID_ACTION`.

`warehouse_state` is WarehouseState (contract §2.1):

```json
{
  "warehouse_id": "demo-warehouse",
  "version": 1,
  "zones": {
    "A": {"inventory": 20, "capacity": 30},
    "B": {"inventory": 8, "capacity": 10},
    "C": {"inventory": 5, "capacity": 20}
  },
  "restricted_zones": ["HAZMAT"]
}
```

HAZMAT is always treated as restricted, even if omitted.

## Output (SimulationResult, contract §3.3)

All five keys are always present.

Pass:

```json
{
  "passed": true,
  "warehouse_version": 1,
  "reason": null,
  "violations": [],
  "projected_state": {
    "A": {"inventory": 15, "capacity": 30},
    "B": {"inventory": 10, "capacity": 10},
    "C": {"inventory": 8, "capacity": 20}
  }
}
```

Fail:

```json
{
  "passed": false,
  "warehouse_version": 1,
  "reason": "Action 1: Zone B would contain 13 packages, exceeding its maximum capacity of 10.",
  "violations": [
    {
      "code": "CAPACITY_EXCEEDED",
      "action_index": 0,
      "zone": "B",
      "projected": 13,
      "capacity": 10,
      "message": "Action 1: Zone B would contain 13 packages, exceeding its maximum capacity of 10."
    }
  ],
  "projected_state": {
    "A": {"inventory": 15, "capacity": 30},
    "B": {"inventory": 13, "capacity": 10},
    "C": {"inventory": 5, "capacity": 20}
  }
}
```

- **Branch on `passed`.** On failure, `projected_state` is a counterfactual, never real inventory. It is `null` only for `INVALID_WAREHOUSE_STATE` / `INTERNAL_ERROR`.
- **`message` is an addition to the contract** (every violation has one). It is written for the replanner: pass `reason` or the `message`s to Bedrock as the rejection reason.
- `action_index` is 0-based; it is `null` for plan-level problems. Messages number actions from 1.
- `INSUFFICIENT_INVENTORY` violations carry `zone`, `available`, `requested`, `projected` instead of `capacity`.

## Violation codes

| Code | Meaning | Replan can fix? |
|---|---|---|
| `CAPACITY_EXCEEDED` | A step pushes a zone over capacity | Yes: smaller count or another destination |
| `INSUFFICIENT_INVENTORY` | A step moves more than the source holds at that point | Yes |
| `UNKNOWN_ZONE` | Zone not in the warehouse | Yes |
| `RESTRICTED_ZONE` | HAZMAT (or another restricted zone) used | Yes, but never by renaming the zone |
| `INVALID_COUNT` | Count not a positive integer (0, negative, float, string, boolean) | Yes |
| `INVALID_ACTION` | Wrong type, missing/extra fields, lowercase label, same source and destination | Yes |
| `INVALID_PLAN` | Not an object, empty, >10 actions, extra top-level fields | Yes |
| `INVALID_WAREHOUSE_STATE` | Warehouse data is malformed or already inconsistent | No: backend/data problem |
| `INTERNAL_ERROR` | Simulator bug; fails closed | No |

## Behaviour to rely on

- **Sequential:** each action uses the previous action's projected state. A→B 2 then A→B 1 fails on action 2 (B = 11/10).
- **Intermediate violations fail the plan**, even if a later action would repair the state.
- **First sequential failure stops evaluation.** Structural problems (shape, count, zones) across all actions are reported together so one replan can fix them all.
- **Count > 10 is not rejected here.** Per contract §2.3 it is schema-valid; `authorize_plan` denies it.
- `simulate_plan` does not classify risk or authorize; call `authorize_plan` and `classify_risk` separately.

## Run locally

From `backend/`:

```
uv run --no-project --python 3.12 --with pytest python -m pytest tests -v   # 61 tests
uv run --no-project --python 3.12 python -m core.simulator                  # 3 demo scenarios
```
