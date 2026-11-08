"""Two bounded model calls, no inventory operations. Author: Tishneet.

Warehouse snapshots and rejection feedback are scripted test inputs. Only the
model outputs are live. Results establish model/schema compatibility, not AWS
workflow, Verified Permissions or production inventory integration.
"""
import argparse
import copy
import getpass
from datetime import datetime, timezone
import json
import os
import sys

from backend.ai.intent import check_intent, parse_instruction
from backend.ai.planner import Planner
from backend.ai.providers import provider_from_env
from backend.ai.validation import validate_plan

MODEL = "amazon.nova-pro-v1:0"
WAREHOUSE = {"warehouse_id": "demo-warehouse", "version": 1,
             "zones": {"A": {"inventory": 20, "capacity": 30},
                       "B": {"inventory": 8, "capacity": 10},
                       "C": {"inventory": 5, "capacity": 20}}, "restricted_zones": ["HAZMAT"]}
ROUTINE = "Move three packages from Zone A to Zone C."
FLEXIBLE = "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary."


def _valid(plan, instruction):
    if not validate_plan(plan)["valid"] or not check_intent(plan, parse_instruction(instruction))["valid"]:
        raise ValueError("Live candidate failed independent validation")


def run_checks(provider):
    if provider.name != "BEDROCK":
        raise ValueError("This check requires Bedrock, never a fixture fallback")
    planner = Planner(provider)
    routine = planner.generate_plan(ROUTINE, WAREHOUSE)
    _valid(routine, ROUTINE)
    routine_metrics = copy.deepcopy(provider.metrics)
    # Canonical D2 snapshot after D1; it is supplied test data, not a real commit.
    current = copy.deepcopy(WAREHOUSE)
    current["version"] = 2
    current["zones"]["A"]["inventory"] = 17
    current["zones"]["C"]["inventory"] = 8
    failed = {"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 5}]}
    failure = {"passed": False, "warehouse_version": 2, "reason": "Zone B would contain13, capacity10",
               "violations": [{"code": "CAPACITY_EXCEEDED", "action_index": 0,
                               "zone": "B", "projected": 13, "capacity": 10}],
               "projected_state": {"A": {"inventory": 12, "capacity": 30},
                                   "B": {"inventory": 13, "capacity": 10},
                                   "C": {"inventory": 8, "capacity": 20}}}
    revised = planner.replan(FLEXIBLE, failed, failure, current, 2)
    _valid(revised, FLEXIBLE)
    # Scenario oracle only: all5 packages originate in A, so destination totals
    # prove this particular bounded split fits. Mariam owns general simulation.
    totals = {"B": 0, "C": 0}
    for action in revised["actions"]:
        if action["to"] not in totals:
            raise ValueError("Replan chose an unknown/restricted destination")
        totals[action["to"]] += action["count"]
    if totals["B"] > 2 or totals["C"] > 12:
        raise ValueError("Replan still violates the scripted capacity constraint")
    return {"provider": provider.name, "model_id": getattr(provider, "model_id", "injected-test-model"),
            "region": os.environ.get("AWS_DEFAULT_REGION"),
            "checked_at": datetime.now(timezone.utc).isoformat(), "model_calls": 2,
            "warehouse_source": "SCRIPTED_DEMO_SNAPSHOTS", "inventory_operations": 0,
            "checks": {"generation_schema_intent": True, "replan_schema_intent_capacity": True},
            "generation_metrics": routine_metrics, "replan_metrics": copy.deepcopy(provider.metrics)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    authentication = parser.add_mutually_exclusive_group()
    authentication.add_argument("--prompt-key", action="store_true",
                                help="Enter a Bedrock key privately in your terminal; never saved to disk.")
    authentication.add_argument("--profile", help="AWS shared-credentials profile for model invocation.")
    parser.add_argument("--region", default=None)
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args(argv)
    if args.prompt_key:
        if not sys.stdin.isatty():
            print("Key entry requires an interactive terminal.", file=sys.stderr)
            return 1
        key = getpass.getpass("Bedrock API key (hidden): ").strip()
        if not key:
            print("No key entered; no request sent.", file=sys.stderr)
            return 1
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = key
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
        # Explicit profile selection must not silently reuse a bearer key.
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    if args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region
    if args.model_id:
        os.environ["BEDROCK_MODEL_ID"] = args.model_id
    os.environ["SENTINEL_MODEL_PROVIDER"] = "bedrock"
    os.environ.setdefault("BEDROCK_MODEL_ID", MODEL)
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    if "amazon.nova-pro-v1:0" in os.environ["BEDROCK_MODEL_ID"]:
        os.environ.setdefault("BEDROCK_FORCE_TOOL", "true")
    try:
        report = run_checks(provider_from_env())
    except Exception:
        print("Bedrock smoke did not pass. Check local credentials, model access, Region and response validation.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
