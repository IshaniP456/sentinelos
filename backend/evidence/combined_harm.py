"""Combined harm: every step passes a per-call check, the whole plan does not.

Per-call controls (for example, a Cedar policy evaluated on each tool call)
see one action at a time: the agent is active, 2 and 1 are under its limit of
10, and Zone B is not restricted. Each action alone also fits Zone B
(8 + 2 = 10, 8 + 1 = 9 of capacity 10). Only checking the WHOLE plan against
the CURRENT state shows that together they put 11 packages into a zone that
holds 10.

Pure Python, no AWS. Run from backend/:
    python -m evidence.combined_harm
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.simulator import simulate_plan
from data.schema import seed_agent, seed_warehouse
from security.authorization import authorize_plan

PLAN_FILE = Path(__file__).with_name("combined_harm_plan.json")


def analyse(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or json.loads(PLAN_FILE.read_text())
    warehouse, agent = seed_warehouse(), seed_agent()
    steps = []
    for index, action in enumerate(plan["actions"]):
        alone = {"actions": [action]}
        steps.append({
            "index": index + 1,
            "action": action,
            "policy_allows_alone": authorize_plan(alone, agent, warehouse["restricted_zones"])["allowed"],
            "fits_alone": simulate_plan(alone, warehouse)["passed"],
        })
    whole = simulate_plan(plan, warehouse)
    return {"steps": steps, "whole_plan_passes": whole["passed"], "whole_plan_reason": whole["reason"]}


def main() -> int:
    report = analyse()
    for step in report["steps"]:
        a = step["action"]
        print(f"Step {step['index']}: move {a['count']} from {a['from']} to {a['to']}  "
              f"policy alone: {'ALLOW' if step['policy_allows_alone'] else 'DENY'}  "
              f"fits alone: {'yes' if step['fits_alone'] else 'no'}")
    print(f"Whole plan against live state: {'PASS' if report['whole_plan_passes'] else 'BLOCKED'}"
          + ("" if report["whole_plan_passes"] else f"  ({report['whole_plan_reason']})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
