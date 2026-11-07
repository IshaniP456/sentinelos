"""Tests for core.simulator.simulate_plan (Team Integration Contract v1.0, section 3.3).

Run from the backend/ directory:  python -m pytest tests -v
"""

import copy
import json

import pytest

from core.simulator import (
    CAPACITY_EXCEEDED,
    INSUFFICIENT_INVENTORY,
    INVALID_ACTION,
    INVALID_COUNT,
    INVALID_PLAN,
    INVALID_WAREHOUSE_STATE,
    RESTRICTED_ZONE,
    UNKNOWN_ZONE,
    simulate_plan,
)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def warehouse() -> dict:
    """Contract section 2.1 seed state. A fresh copy for every test."""
    return {
        "warehouse_id": "demo-warehouse",
        "version": 1,
        "zones": {
            "A": {"inventory": 20, "capacity": 30},
            "B": {"inventory": 8, "capacity": 10},
            "C": {"inventory": 5, "capacity": 20},
        },
        "restricted_zones": ["HAZMAT"],
    }


def move(source, destination, count, **extra) -> dict:
    """Build one move_packages action."""
    return {"type": "move_packages", "from": source, "to": destination, "count": count, **extra}


def plan(*actions) -> dict:
    """Build a PlanActions payload."""
    return {"actions": list(actions)}


def codes(result: dict) -> list[str]:
    return [v["code"] for v in result["violations"]]


def inventories(result: dict) -> dict[str, int]:
    return {zone: z["inventory"] for zone, z in result["projected_state"].items()}


def assert_failed_with(result: dict, code: str) -> None:
    assert result["passed"] is False
    assert code in codes(result), result["violations"]
    assert isinstance(result["reason"], str) and result["reason"]


# ------------------------------------------------------------- required: passing plans


def test_move_3_from_a_to_c_passes(warehouse):
    result = simulate_plan(plan(move("A", "C", 3)), warehouse)

    assert result == {
        "passed": True,
        "warehouse_version": 1,
        "reason": None,
        "violations": [],
        "projected_state": {
            "A": {"inventory": 17, "capacity": 30},
            "B": {"inventory": 8, "capacity": 10},
            "C": {"inventory": 8, "capacity": 20},
        },
    }


def test_move_2_from_a_to_b_passes(warehouse):
    result = simulate_plan(plan(move("A", "B", 2)), warehouse)

    assert result["passed"] is True
    assert inventories(result) == {"A": 18, "B": 10, "C": 5}


def test_multiple_valid_sequential_actions_pass(warehouse):
    """Contract section 3.3 success example: the D2 split (2 to B, 3 to C)."""
    result = simulate_plan(plan(move("A", "B", 2), move("A", "C", 3)), warehouse)

    assert result == {
        "passed": True,
        "warehouse_version": 1,
        "reason": None,
        "violations": [],
        "projected_state": {
            "A": {"inventory": 15, "capacity": 30},
            "B": {"inventory": 10, "capacity": 10},
            "C": {"inventory": 8, "capacity": 20},
        },
    }


# ------------------------------------------------------- required: capacity failures


def test_move_5_from_a_to_b_fails_capacity(warehouse):
    """Contract section 3.3 failure example, including the counterfactual projection."""
    result = simulate_plan(plan(move("A", "B", 5)), warehouse)

    assert result["passed"] is False
    assert result["warehouse_version"] == 1
    assert result["violations"] == [
        {
            "code": CAPACITY_EXCEEDED,
            "action_index": 0,
            "zone": "B",
            "projected": 13,
            "capacity": 10,
            "message": "Action 1: Zone B would contain 13 packages, "
            "exceeding its maximum capacity of 10.",
        }
    ]
    assert result["reason"] == result["violations"][0]["message"]
    assert result["projected_state"] == {
        "A": {"inventory": 15, "capacity": 30},
        "B": {"inventory": 13, "capacity": 10},
        "C": {"inventory": 5, "capacity": 20},
    }


def test_move_2_then_1_from_a_to_b_fails_cumulative_capacity(warehouse):
    result = simulate_plan(plan(move("A", "B", 2), move("A", "B", 1)), warehouse)

    assert_failed_with(result, CAPACITY_EXCEEDED)
    [violation] = result["violations"]
    assert violation["action_index"] == 1  # the first action alone was fine
    assert violation["projected"] == 11
    assert violation["capacity"] == 10


# ------------------------------------------------------------ required: bad counts


@pytest.mark.parametrize(
    "count",
    [
        pytest.param(-3, id="negative"),
        pytest.param(0, id="zero"),
        pytest.param(2.5, id="float"),
        pytest.param(3.0, id="whole-float"),
        pytest.param("3", id="string"),
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param(None, id="null"),
    ],
)
def test_invalid_counts_fail(warehouse, count):
    result = simulate_plan(plan(move("A", "C", count)), warehouse)

    assert_failed_with(result, INVALID_COUNT)
    assert inventories(result) == {"A": 20, "B": 8, "C": 5}  # nothing applied


def test_move_negative_3_from_a_to_c_fails(warehouse):
    """Named case from the plan: A -> C, -3 packages."""
    assert_failed_with(simulate_plan(plan(move("A", "C", -3)), warehouse), INVALID_COUNT)


def test_boolean_count_is_rejected_even_though_python_treats_it_as_int(warehouse):
    assert isinstance(True, int)  # the trap this guards against
    assert_failed_with(simulate_plan(plan(move("A", "C", True)), warehouse), INVALID_COUNT)


# ------------------------------------------------------------- required: bad zones


def test_unknown_source_zone_fails(warehouse):
    result = simulate_plan(plan(move("Z", "C", 1)), warehouse)

    assert_failed_with(result, UNKNOWN_ZONE)
    assert result["violations"][0]["zone"] == "Z"


def test_unknown_destination_zone_fails(warehouse):
    result = simulate_plan(plan(move("A", "D", 1)), warehouse)

    assert_failed_with(result, UNKNOWN_ZONE)
    assert result["violations"][0]["zone"] == "D"


def test_move_into_hazmat_fails_as_restricted_not_unknown(warehouse):
    result = simulate_plan(plan(move("A", "HAZMAT", 1)), warehouse)

    assert_failed_with(result, RESTRICTED_ZONE)
    assert UNKNOWN_ZONE not in codes(result)
    assert result["violations"][0]["zone"] == "HAZMAT"


def test_hazmat_is_restricted_even_if_state_omits_it(warehouse):
    del warehouse["restricted_zones"]

    assert_failed_with(simulate_plan(plan(move("A", "HAZMAT", 1)), warehouse), RESTRICTED_ZONE)


def test_move_out_of_hazmat_fails(warehouse):
    assert_failed_with(simulate_plan(plan(move("HAZMAT", "A", 1)), warehouse), RESTRICTED_ZONE)


def test_transfer_from_zone_to_itself_fails(warehouse):
    assert_failed_with(simulate_plan(plan(move("A", "A", 1)), warehouse), INVALID_ACTION)


def test_lowercase_zone_label_fails(warehouse):
    assert_failed_with(simulate_plan(plan(move("a", "C", 1)), warehouse), INVALID_ACTION)


# ------------------------------------------------------ required: insufficient stock


def test_insufficient_source_inventory_fails(warehouse):
    result = simulate_plan(plan(move("C", "A", 6)), warehouse)  # C only has 5

    assert_failed_with(result, INSUFFICIENT_INVENTORY)
    violation = result["violations"][0]
    assert violation["zone"] == "C"
    assert violation["available"] == 5
    assert violation["requested"] == 6


def test_insufficient_inventory_is_cumulative(warehouse):
    """Second move fails because the first already drained C."""
    result = simulate_plan(plan(move("C", "A", 4), move("C", "B", 2)), warehouse)

    assert_failed_with(result, INSUFFICIENT_INVENTORY)
    assert result["violations"][0]["action_index"] == 1
    assert result["violations"][0]["available"] == 1


# ----------------------------------------------------- required: malformed structure


def test_unsupported_action_type_fails(warehouse):
    action = move("A", "C", 1)
    action["type"] = "delete_zone"

    assert_failed_with(simulate_plan(plan(action), warehouse), INVALID_ACTION)


def test_empty_actions_array_fails(warehouse):
    assert_failed_with(simulate_plan(plan(), warehouse), INVALID_PLAN)


@pytest.mark.parametrize("missing", ["type", "from", "to", "count"])
def test_missing_required_field_fails(warehouse, missing):
    action = move("A", "C", 1)
    del action[missing]

    result = simulate_plan(plan(action), warehouse)

    assert_failed_with(result, INVALID_ACTION)
    assert missing in result["reason"]


@pytest.mark.parametrize(
    "bad_plan",
    [
        pytest.param(None, id="none"),
        pytest.param("move 3 from A to C", id="string"),
        pytest.param([move("A", "C", 1)], id="bare-list"),
        pytest.param({}, id="no-actions-key"),
        pytest.param({"actions": "A->C"}, id="actions-not-list"),
        pytest.param({"actions": None}, id="actions-null"),
        pytest.param({"actions": [move("A", "C", 1)], "approved": True}, id="extra-plan-field"),
    ],
)
def test_malformed_plan_structure_fails(warehouse, bad_plan):
    assert_failed_with(simulate_plan(bad_plan, warehouse), INVALID_PLAN)


def test_non_object_action_fails(warehouse):
    assert_failed_with(simulate_plan(plan("A->C"), warehouse), INVALID_ACTION)


def test_extra_action_field_fails(warehouse):
    """Contract 2.3: exactly type, from, to, count. AI-supplied flags carry no authority."""
    result = simulate_plan(plan(move("A", "C", 1, authorized=True)), warehouse)

    assert_failed_with(result, INVALID_ACTION)
    assert "authorized" in result["reason"]


def test_more_than_ten_actions_fails(warehouse):
    actions = [move("A", "C", 1) for _ in range(11)]

    assert_failed_with(simulate_plan(plan(*actions), warehouse), INVALID_PLAN)


def test_exactly_ten_actions_is_allowed(warehouse):
    actions = [move("A", "C", 1) for _ in range(10)]

    result = simulate_plan(plan(*actions), warehouse)

    assert result["passed"] is True
    assert inventories(result) == {"A": 10, "B": 8, "C": 15}


def test_all_structural_problems_are_reported_together(warehouse):
    """Lets the replanner fix every problem in one attempt."""
    result = simulate_plan(plan(move("A", "HAZMAT", 1), move("A", "C", 0)), warehouse)

    assert result["passed"] is False
    assert codes(result) == [RESTRICTED_ZONE, INVALID_COUNT]
    assert [v["action_index"] for v in result["violations"]] == [0, 1]


# --------------------------------------------- required: original state never changes


def test_original_warehouse_unchanged_after_passing_plan(warehouse):
    before = copy.deepcopy(warehouse)

    result = simulate_plan(plan(move("A", "C", 3)), warehouse)

    assert result["passed"] is True
    assert warehouse == before
    assert warehouse["zones"]["A"]["inventory"] == 20
    assert warehouse["zones"]["B"]["inventory"] == 8
    assert warehouse["zones"]["C"]["inventory"] == 5


def test_original_warehouse_unchanged_after_failing_plan(warehouse):
    before = copy.deepcopy(warehouse)

    result = simulate_plan(plan(move("A", "B", 2), move("A", "B", 1)), warehouse)

    assert result["passed"] is False
    assert warehouse == before


def test_original_plan_unchanged(warehouse):
    p = plan(move("A", "B", 2), move("A", "C", 3))
    before = copy.deepcopy(p)

    simulate_plan(p, warehouse)

    assert p == before


def test_projected_state_shares_no_objects_with_input(warehouse):
    result = simulate_plan(plan(move("A", "C", 3)), warehouse)

    result["projected_state"]["A"]["inventory"] = 999

    assert warehouse["zones"]["A"]["inventory"] == 20


# ------------------------------------------------ required: different configuration


def test_works_with_a_different_warehouse_configuration():
    other = {
        "version": 7,
        "zones": {
            "NORTH": {"inventory": 50, "capacity": 60},
            "SOUTH": {"inventory": 0, "capacity": 5},
        },
        "restricted_zones": ["COLD"],
    }

    ok = simulate_plan(plan(move("NORTH", "SOUTH", 5)), other)
    too_many = simulate_plan(plan(move("NORTH", "SOUTH", 6)), other)
    restricted = simulate_plan(plan(move("NORTH", "COLD", 1)), other)
    seed_zone = simulate_plan(plan(move("A", "B", 1)), other)

    assert ok["passed"] is True
    assert ok["warehouse_version"] == 7
    assert inventories(ok) == {"NORTH": 45, "SOUTH": 5}
    assert_failed_with(too_many, CAPACITY_EXCEEDED)
    assert too_many["violations"][0]["capacity"] == 5
    assert_failed_with(restricted, RESTRICTED_ZONE)
    assert_failed_with(seed_zone, UNKNOWN_ZONE)


# ------------------------------------------------------- PRD edge cases and contract


def test_intermediate_violation_fails_even_if_later_step_repairs_it(warehouse):
    """PRD FR04: B goes to 13 at step 1; step 2 would bring it back to 9."""
    result = simulate_plan(plan(move("A", "B", 5), move("B", "C", 4)), warehouse)

    assert_failed_with(result, CAPACITY_EXCEEDED)
    assert result["violations"][0]["action_index"] == 0


def test_count_above_ten_is_left_to_authorization(warehouse):
    """Contract 2.3: count > 10 is schema-valid; authorize_plan denies it, not the simulator."""
    result = simulate_plan(plan(move("A", "C", 11)), warehouse)

    assert result["passed"] is True
    assert inventories(result) == {"A": 9, "B": 8, "C": 16}


def test_total_inventory_is_conserved(warehouse):
    result = simulate_plan(plan(move("A", "B", 2), move("A", "C", 3), move("C", "A", 1)), warehouse)

    assert result["passed"] is True
    assert sum(inventories(result).values()) == 33


def test_same_input_gives_same_result(warehouse):
    p = plan(move("A", "B", 2), move("A", "B", 1))

    assert simulate_plan(p, warehouse) == simulate_plan(p, warehouse)


@pytest.mark.parametrize(
    "p",
    [
        pytest.param(plan(move("A", "C", 3)), id="pass"),
        pytest.param(plan(move("A", "B", 5)), id="fail"),
        pytest.param(None, id="malformed"),
    ],
)
def test_result_is_json_serializable_with_all_contract_keys(warehouse, p):
    result = simulate_plan(p, warehouse)

    assert json.loads(json.dumps(result)) == result
    assert set(result) == {"passed", "warehouse_version", "reason", "violations", "projected_state"}


@pytest.mark.parametrize(
    "bad_state",
    [
        pytest.param(None, id="none"),
        pytest.param({"version": 1}, id="no-zones"),
        pytest.param({"version": 1, "zones": {}}, id="empty-zones"),
        pytest.param({"zones": {"A": {"inventory": "20", "capacity": 30}}}, id="string-inventory"),
        pytest.param({"zones": {"A": {"inventory": 31, "capacity": 30}}}, id="over-capacity"),
        pytest.param({"zones": {"A": {"inventory": -1, "capacity": 30}}}, id="negative"),
        pytest.param(
            {"zones": {"A": {"inventory": 1, "capacity": 30}}, "restricted_zones": "HAZMAT"},
            id="restricted-not-list",
        ),
    ],
)
def test_invalid_warehouse_state_fails_closed(bad_state):
    result = simulate_plan(plan(move("A", "B", 1)), bad_state)

    assert_failed_with(result, INVALID_WAREHOUSE_STATE)
