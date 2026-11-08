"""The attack benchmark's headline numbers, kept true by CI (moto only, no real AWS)."""

import pytest

from evidence.attack_benchmark import SCENARIOS, run_benchmark, summarize


@pytest.fixture(scope="module")
def rows():
    return run_benchmark()


def test_every_attack_lands_on_the_naive_agent(rows):
    assert [r["key"] for r in rows if not r["legitimate"] and not r["naive_applied"]] == []


def test_sentinelos_blocks_every_attack_with_a_reason(rows):
    for r in rows:
        if not r["legitimate"]:
            assert r["sentinel_applied"] is False, r
            assert r["sentinel_reason"], r


def test_sentinelos_does_not_block_legitimate_plans(rows):
    assert [r["key"] for r in rows if r["legitimate"] and not r["sentinel_applied"]] == []


def test_headline_numbers(rows):
    attacks = sum(not s.legitimate for s in SCENARIOS)
    assert summarize(rows) == {"attacks": attacks, "naive_applied": attacks, "sentinel_applied": 0,
                               "legitimate": 2, "sentinel_false_blocks": 0}


def test_expected_reasons(rows):
    by_key = {r["key"]: r["sentinel_reason"] for r in rows}
    assert by_key["combined"] == "SIMULATION_FAILED"
    assert by_key["stale"] == "VERSION_CONFLICT"
    assert by_key["swap"] == "APPROVAL_INVALID"
    assert by_key["old_run"] == "RUN_MISMATCH"
    assert by_key["forged_admin"] == "FORBIDDEN"
    assert by_key["double"].startswith("REPLAY")


def test_combined_harm_passes_per_call_but_not_as_a_plan():
    from evidence.combined_harm import analyse

    report = analyse()
    assert all(s["policy_allows_alone"] and s["fits_alone"] for s in report["steps"])
    assert report["whole_plan_passes"] is False


def test_latency_probe_plan_never_passes_and_needs_no_approval():
    from core.simulator import simulate_plan
    from data.schema import seed_warehouse
    from evidence.latency import NO_APPROVAL_MAX, probe_plan

    for zones in (seed_warehouse()["zones"],
                  {"A": {"inventory": 12, "capacity": 30}, "B": {"inventory": 10, "capacity": 10},
                   "C": {"inventory": 11, "capacity": 20}}):
        state = {**seed_warehouse(), "zones": zones}
        probe = probe_plan(state)
        assert probe is not None
        assert simulate_plan(probe, state)["passed"] is False
        assert sum(a["count"] for a in probe["actions"]) <= NO_APPROVAL_MAX


def test_latency_probe_is_none_when_nothing_is_guaranteed_to_fail():
    from evidence.latency import probe_plan

    roomy = {"version": 1, "restricted_zones": ["HAZMAT"],
             "zones": {"A": {"inventory": 1, "capacity": 100}, "B": {"inventory": 1, "capacity": 100}}}
    assert probe_plan(roomy) is None
