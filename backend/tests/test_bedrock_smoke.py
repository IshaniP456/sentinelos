"""Check the live-model probe's independent oracle offline. Author: Tishneet."""
import copy

import pytest

from backend.ai.providers import FixtureProvider
from scripts.bedrock_smoke import run_checks


class ModelDouble:
    name = "BEDROCK"
    metrics = {}

    def __init__(self, destination="C", count=5):
        self.destination, self.count = destination, count
        self.calls = 0

    def generate(self, instruction, warehouse, **kwargs):
        self.calls += 1
        destination = "C" if self.calls == 1 else self.destination
        count = 3 if self.calls == 1 else self.count
        return copy.deepcopy({"actions": [{"type": "move_packages", "from": "A",
                                            "to": destination, "count": count}]})


def test_probe_requires_bedrock():
    with pytest.raises(ValueError, match="never a fixture"):
        run_checks(FixtureProvider())


def test_probe_accepts_valid_replan_in_exactly_two_calls():
    provider = ModelDouble()
    report = run_checks(provider)
    assert provider.calls == report["model_calls"] == 2
    assert report["inventory_operations"] == 0
    assert all(report["checks"].values())


@pytest.mark.parametrize("destination,count", [("B", 5), ("HAZMAT", 5), ("C", 4)])
def test_probe_rejects_capacity_restriction_or_intent_failure(destination, count):
    with pytest.raises(ValueError):
        run_checks(ModelDouble(destination, count))
