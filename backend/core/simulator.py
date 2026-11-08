"""Deterministic warehouse plan simulator for SentinelOS.

Implements ``simulate_plan`` as defined in the Team Integration Contract v1.0:

* Input ``plan``            -> section 2.3 PlanActions
* Input ``warehouse_state`` -> section 2.1 WarehouseState
* Output                    -> section 3.3 SimulationResult

The simulator is a pure function. It performs no I/O, makes no AWS calls,
never mutates its arguments, and always returns the same result for the same
inputs. It does not decide authorization: an action count above 10 is
schema-valid here and is denied separately by ``authorize_plan``.

Evaluation happens in two passes:

1. Structural pass. The plan and every action are checked for shape, count,
   zone-label form, restricted zones, and unknown zones. All problems found
   are reported together so a replanner can fix them in one attempt.
2. Sequential pass. Actions are applied in order to an isolated copy of the
   inventory. Each step uses the previous step's projected state. The first
   step that leaves a zone negative or over capacity fails the whole plan,
   even if a later step would have repaired it.
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

ACTION_TYPE = "move_packages"
ACTION_KEYS = frozenset({"type", "from", "to", "count"})
PLAN_KEYS = frozenset({"actions"})
MIN_ACTIONS = 1
MAX_ACTIONS = 10
ALWAYS_RESTRICTED_ZONES = frozenset({"HAZMAT"})
ZONE_LABEL_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Violation codes (machine-readable, UPPER_SNAKE_CASE per the contract).
INVALID_PLAN = "INVALID_PLAN"
INVALID_ACTION = "INVALID_ACTION"
INVALID_COUNT = "INVALID_COUNT"
UNKNOWN_ZONE = "UNKNOWN_ZONE"
RESTRICTED_ZONE = "RESTRICTED_ZONE"
INSUFFICIENT_INVENTORY = "INSUFFICIENT_INVENTORY"
CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
INVALID_WAREHOUSE_STATE = "INVALID_WAREHOUSE_STATE"
INTERNAL_ERROR = "INTERNAL_ERROR"

Violation = dict[str, Any]
ProjectedState = dict[str, dict[str, int]]


def simulate_plan(plan: Any, warehouse_state: Any) -> dict[str, Any]:
    """Simulate a plan against a warehouse state without changing either.

    Args:
        plan: PlanActions, e.g.
            ``{"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 5}]}``.
        warehouse_state: WarehouseState, e.g.
            ``{"version": 1, "zones": {"A": {"inventory": 20, "capacity": 30}, ...},
            "restricted_zones": ["HAZMAT"]}``.

    Returns:
        A JSON-serializable SimulationResult with these keys:

        * ``passed`` (bool): True only if every action is valid in sequence.
        * ``warehouse_version`` (int | None): the version that was simulated against.
        * ``reason`` (str | None): readable summary of the first violation, None on pass.
        * ``violations`` (list): every violation found, each with ``code``,
          ``action_index`` (0-based, or None for plan-level problems) and ``message``,
          plus ``zone``/``projected``/``capacity`` or ``available``/``requested``
          where relevant.
        * ``projected_state`` (dict | None): zone -> {inventory, capacity}. On failure
          it is a counterfactual (never committed). None if the warehouse state
          itself was unusable.

    Malformed input never raises. It produces ``passed: False`` instead (fail closed).
    """
    try:
        return _simulate(plan, warehouse_state)
    except Exception:  # Defensive: a simulator bug must never be read as a pass.
        logger.exception("simulate_plan raised unexpectedly; failing closed")
        violation = _violation(
            INTERNAL_ERROR, None, "Internal simulator error. The plan was not evaluated."
        )
        return _result(None, [violation], None)


def _simulate(plan: Any, warehouse_state: Any) -> dict[str, Any]:
    """Run both passes. Assumes nothing about input shape."""
    state_errors, version, zones, restricted = _read_warehouse_state(warehouse_state)
    if state_errors:
        return _result(version, state_errors, None)

    # Isolated working copy: fresh dicts of plain ints, nothing shared with the input.
    projected: ProjectedState = {
        name: {"inventory": z["inventory"], "capacity": z["capacity"]}
        for name, z in zones.items()
    }

    structural = _check_structure(plan, set(zones), restricted)
    if structural:
        return _result(version, structural, projected)

    for index, action in enumerate(plan["actions"]):
        step_violations = _apply_action(projected, index, action)
        if step_violations:
            return _result(version, step_violations, projected)

    return _result(version, [], projected)


def _read_warehouse_state(
    state: Any,
) -> tuple[list[Violation], int | None, dict[str, dict[str, int]], frozenset[str]]:
    """Validate a WarehouseState and extract version, zones, and restricted zones.

    A state that is already inconsistent (negative or over-capacity zones) is
    rejected rather than simulated: the simulator fails closed on bad data.
    """
    errors: list[Violation] = []

    def bad(message: str) -> None:
        errors.append(_violation(INVALID_WAREHOUSE_STATE, None, message))

    if not isinstance(state, Mapping):
        bad("Warehouse state must be an object.")
        return errors, None, {}, ALWAYS_RESTRICTED_ZONES

    raw_version = state.get("version")
    version = raw_version if _is_plain_int(raw_version) else None

    raw_zones = state.get("zones")
    if not isinstance(raw_zones, Mapping) or not raw_zones:
        bad("Warehouse state must contain a non-empty 'zones' object.")
        return errors, version, {}, ALWAYS_RESTRICTED_ZONES

    zones: dict[str, dict[str, int]] = {}
    for name, zone in raw_zones.items():
        if not isinstance(name, str) or not isinstance(zone, Mapping):
            bad(f"Zone {name!r} must be a named object with inventory and capacity.")
            continue
        inventory, capacity = zone.get("inventory"), zone.get("capacity")
        if not (_is_plain_int(inventory) and _is_plain_int(capacity)):
            bad(f"Zone {name} must have integer 'inventory' and 'capacity'.")
            continue
        if capacity < 0 or inventory < 0 or inventory > capacity:
            bad(
                f"Zone {name} is already inconsistent: inventory {inventory}, "
                f"capacity {capacity}."
            )
            continue
        zones[name] = {"inventory": inventory, "capacity": capacity}

    raw_restricted = state.get("restricted_zones", [])
    if not isinstance(raw_restricted, list) or not all(
        isinstance(z, str) for z in raw_restricted
    ):
        bad("'restricted_zones' must be a list of zone names.")
        raw_restricted = []
    # HAZMAT is always restricted, even if a caller forgets to list it.
    restricted = frozenset(raw_restricted) | ALWAYS_RESTRICTED_ZONES

    return errors, version, zones, restricted


def _check_structure(
    plan: Any, zone_names: set[str], restricted: frozenset[str]
) -> list[Violation]:
    """Check plan and action shape plus zone references. Returns every problem found."""
    if not isinstance(plan, Mapping):
        return [_violation(INVALID_PLAN, None, "Plan must be an object with an 'actions' list.")]

    extra_plan_keys = sorted(set(plan) - PLAN_KEYS, key=str)
    if extra_plan_keys:
        return [
            _violation(
                INVALID_PLAN,
                None,
                f"Plan contains unexpected fields {extra_plan_keys}. Only 'actions' is allowed.",
            )
        ]

    actions = plan.get("actions")
    if not isinstance(actions, list):
        return [_violation(INVALID_PLAN, None, "Plan must contain an 'actions' list.")]
    if len(actions) < MIN_ACTIONS:
        return [_violation(INVALID_PLAN, None, "Plan must contain at least one action.")]
    if len(actions) > MAX_ACTIONS:
        return [
            _violation(
                INVALID_PLAN,
                None,
                f"Plan contains {len(actions)} actions; the maximum is {MAX_ACTIONS}.",
            )
        ]

    violations: list[Violation] = []
    for index, action in enumerate(actions):
        violations.extend(_check_action(index, action, zone_names, restricted))
    return violations


def _check_action(
    index: int, action: Any, zone_names: set[str], restricted: frozenset[str]
) -> list[Violation]:
    """Check one action's shape, count, and zones. Returns all problems for it."""
    label = f"Action {index + 1}"
    if not isinstance(action, Mapping):
        return [_violation(INVALID_ACTION, index, f"{label}: must be an object.")]

    keys = set(action)
    missing = sorted(ACTION_KEYS - keys)
    extra = sorted(keys - ACTION_KEYS, key=str)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing fields {missing}")
        if extra:
            parts.append(f"unexpected fields {extra}")
        return [
            _violation(
                INVALID_ACTION,
                index,
                f"{label}: {' and '.join(parts)}. Required fields are type, from, to, count.",
            )
        ]

    violations: list[Violation] = []

    if action["type"] != ACTION_TYPE:
        violations.append(
            _violation(
                INVALID_ACTION,
                index,
                f"{label}: unsupported type {action['type']!r}. Only '{ACTION_TYPE}' is allowed.",
            )
        )

    count = action["count"]
    if not (_is_plain_int(count) and count >= 1):
        violations.append(
            _violation(
                INVALID_COUNT,
                index,
                f"{label}: count must be a positive whole number, got {count!r}.",
            )
        )

    source, destination = action["from"], action["to"]
    labels_ok = True
    for field, zone in (("from", source), ("to", destination)):
        if not (isinstance(zone, str) and ZONE_LABEL_PATTERN.match(zone)):
            labels_ok = False
            violations.append(
                _violation(
                    INVALID_ACTION,
                    index,
                    f"{label}: '{field}' must be an uppercase zone label, got {zone!r}.",
                )
            )
    if not labels_ok:
        return violations

    if source == destination:
        violations.append(
            _violation(
                INVALID_ACTION,
                index,
                f"{label}: source and destination are both {source}; they must differ.",
            )
        )

    for role, zone in (("destination", destination), ("source", source)):
        if zone in restricted:
            violations.append(
                _violation(
                    RESTRICTED_ZONE,
                    index,
                    f"{label}: {zone} is a restricted zone and cannot be used as a {role}.",
                    zone=zone,
                )
            )
        elif zone not in zone_names:
            violations.append(
                _violation(
                    UNKNOWN_ZONE,
                    index,
                    f"{label}: {role} zone {zone} does not exist. "
                    f"Valid zones are {sorted(zone_names)}.",
                    zone=zone,
                )
            )
    return violations


def _apply_action(projected: ProjectedState, index: int, action: Mapping[str, Any]) -> list[Violation]:
    """Apply one structurally valid action to the projected state.

    The action is always applied, so on failure ``projected`` shows the
    counterfactual result of the violating step. Returns that step's violations.
    """
    label = f"Action {index + 1}"
    source, destination, count = action["from"], action["to"], action["count"]
    src, dst = projected[source], projected[destination]
    available = src["inventory"]

    src["inventory"] -= count
    dst["inventory"] += count

    violations: list[Violation] = []
    if src["inventory"] < 0:
        violations.append(
            _violation(
                INSUFFICIENT_INVENTORY,
                index,
                f"{label}: Zone {source} has {available} packages at this step "
                f"but the action moves {count}.",
                zone=source,
                available=available,
                requested=count,
                projected=src["inventory"],
            )
        )
    if dst["inventory"] > dst["capacity"]:
        violations.append(
            _violation(
                CAPACITY_EXCEEDED,
                index,
                f"{label}: Zone {destination} would contain {dst['inventory']} packages, "
                f"exceeding its maximum capacity of {dst['capacity']}.",
                zone=destination,
                projected=dst["inventory"],
                capacity=dst["capacity"],
            )
        )
    return violations


def _violation(code: str, action_index: int | None, message: str, **details: Any) -> Violation:
    """Build one violation entry in contract order: code, action_index, details, message."""
    return {"code": code, "action_index": action_index, **details, "message": message}


def _result(
    version: int | None, violations: list[Violation], projected: ProjectedState | None
) -> dict[str, Any]:
    """Build a SimulationResult (contract section 3.3)."""
    passed = not violations
    return {
        "passed": passed,
        "warehouse_version": version,
        "reason": None if passed else violations[0]["message"],
        "violations": violations,
        "projected_state": projected,
    }


def _is_plain_int(value: Any) -> bool:
    """True for real ints only. Rejects bool (a subclass of int), floats, and strings."""
    return type(value) is int


if __name__ == "__main__":
    import json

    demo_warehouse = {
        "warehouse_id": "demo-warehouse",
        "version": 1,
        "zones": {
            "A": {"inventory": 20, "capacity": 30},
            "B": {"inventory": 8, "capacity": 10},
            "C": {"inventory": 5, "capacity": 20},
        },
        "restricted_zones": ["HAZMAT"],
    }
    scenarios = {
        "A -> C x3": [("A", "C", 3)],
        "A -> B x5": [("A", "B", 5)],
        "A -> B x2, then A -> B x1": [("A", "B", 2), ("A", "B", 1)],
    }
    for title, moves in scenarios.items():
        demo_plan = {
            "actions": [
                {"type": ACTION_TYPE, "from": s, "to": d, "count": n} for s, d, n in moves
            ]
        }
        print(f"=== {title} ===")
        print(json.dumps(simulate_plan(demo_plan, demo_warehouse), indent=2))
    print("=== original warehouse after all simulations ===")
    print(json.dumps(demo_warehouse["zones"]))
