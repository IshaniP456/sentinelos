"""Check the live-model probe's independent oracle offline. Author: Tishneet."""
import copy
from types import SimpleNamespace

import pytest

from backend.ai.providers import FixtureProvider
from scripts.bedrock_smoke import run_checks
from scripts import bedrock_smoke
from scripts.aws_preflight import check_identity


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


def test_private_key_prompt_runs_probe_without_printing_key(monkeypatch, capsys):
    monkeypatch.setattr(bedrock_smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(bedrock_smoke.getpass, "getpass", lambda prompt: "private-test-token")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "previous-token")
    monkeypatch.setattr(bedrock_smoke, "provider_from_env", lambda: ModelDouble())
    assert bedrock_smoke.main(["--prompt-key", "--region", "us-east-1"]) == 0
    captured = capsys.readouterr()
    assert "private-test-token" not in captured.out + captured.err
    assert '"provider": "BEDROCK"' in captured.out


def test_key_prompt_refuses_noninteractive_input(monkeypatch, capsys):
    monkeypatch.setattr(bedrock_smoke.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(bedrock_smoke, "provider_from_env", lambda: pytest.fail("must not call model"))
    assert bedrock_smoke.main(["--prompt-key"]) == 1
    assert "interactive terminal" in capsys.readouterr().err


def test_profile_selection_does_not_reuse_bearer_key(monkeypatch):
    import os
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "old-token")
    monkeypatch.setenv("AWS_PROFILE", "old-profile")
    def provider():
        assert os.environ["AWS_PROFILE"] == "workshop"
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ
        return ModelDouble()
    monkeypatch.setattr(bedrock_smoke, "provider_from_env", provider)
    assert bedrock_smoke.main(["--profile", "workshop"]) == 0


def identity_session(account="737876441172", region="us-east-1"):
    client = SimpleNamespace(get_caller_identity=lambda: {"Account": account})
    return SimpleNamespace(region_name=region, client=lambda service, **kwargs: client)


def test_deployment_identity_gate_reports_account_without_claiming_permissions():
    report = check_identity(identity_session())
    assert report["identity_verified"] is True
    assert report["deployment_permissions_verified"] is False
    assert report["resources_created"] == 0


@pytest.mark.parametrize("account,region", [("123456789012", "us-east-1"), ("737876441172", "us-west-2")])
def test_deployment_identity_gate_stops_for_wrong_account_or_region(account, region):
    with pytest.raises(ValueError):
        check_identity(identity_session(account, region))
