"""Image transport, provenance and unchanged policy gates. Author: Tishneet."""
import base64
import copy
import json

import pytest

from backend.ai.image_input import DEMO_MODE, demo_image, validate_image
from backend.ai.planner import Planner
from backend.ai.providers import BedrockProvider, ScriptedProvider
from backend.tests.test_gateway_contracts import GatewayDouble
from backend.workflows.errors import WorkflowError
from backend.workflows.service import WorkflowService
from backend.workflows.store import MemoryStore


def encoded():
    return base64.b64encode(demo_image()).decode("ascii")


def response(count=11, instruction="Move 11 packages from Zone A to Zone C."):
    return {"stopReason": "tool_use", "usage": {"inputTokens": 12, "outputTokens": 15},
            "output": {"message": {"content": [{"toolUse": {"name": "propose_image_plan", "input": {
                "instruction": instruction, "plan": {"actions": [
                    {"type": "move_packages", "from": "A", "to": "C", "count": count}]}}}}]}}}


class Client:
    def __init__(self, result=None):
        self.result = response() if result is None else result
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        return copy.deepcopy(self.result)


class DenyGateway(GatewayDouble):
    def authorize_plan(self, plan):
        assert plan["actions"][0]["count"] > 10
        return {"allowed": False, "engine": "TEST_POLICY", "decisions": [
            {"action_index": 0, "allowed": False, "reason_code": "LIMIT_EXCEEDED"}]}

    def simulate_plan(self, *args):
        pytest.fail("Authorization denial must stop before simulation")

    def execute_plan(self, **kwargs):
        pytest.fail("Authorization denial must stop before execution")


def make_service(client=None, scripted=False):
    provider = ScriptedProvider([]) if scripted else BedrockProvider(client or Client(), "amazon.nova-pro-v1:0", True)
    return WorkflowService(MemoryStore(), Planner(provider), DenyGateway(), image_demo_enabled=scripted)


def finish(service, plan_id):
    for _ in range(10):
        service.tick(plan_id)
        result = service.get_plan_status(plan_id)
        if result["status"] in {"REJECTED", "FAILED", "COMPLETED"}:
            return result
    pytest.fail("Image workflow did not finish")


def test_png_dimensions_and_digest_are_bounded_and_no_mutation():
    value = validate_image(encoded(), "image/png")
    assert (value["width"], value["height"]) == (1000, 440)
    assert value["size_bytes"] == len(demo_image())
    assert len(value["sha256"]) == 64


@pytest.mark.parametrize("data,mime", [("!invalid", "image/png"), ("", "image/png"),
    ("data:image/png;base64,AAA=", "image/png"), ("A" * 180000, "image/png"),
    (encoded(), "image/svg+xml"), (encoded(), "image/jpeg"), (None, "image/png")])
def test_bad_upload_is_rejected_before_plan_or_model(data, mime):
    client = Client(); service = make_service(client)
    with pytest.raises(WorkflowError) as error:
        service.start_image_plan(data, mime)
    assert error.value.code == "INVALID_REQUEST"
    assert not service.store.list("PLAN#")
    assert not client.requests


def test_live_transport_uses_binary_image_and_normal_authorization_denies():
    client = Client(); service = make_service(client)
    plan_id = service.start_image_plan(encoded(), "image/png")["plan_id"]
    for _ in range(3):
        assert service.get_plan_status(plan_id)["status"] == "PLANNING"
    assert not client.requests
    result = finish(service, plan_id)
    assert result["status"] == "REJECTED"
    assert result["candidates"][0]["validation"]["valid"] is True
    assert result["candidates"][0]["authorization"]["allowed"] is False
    assert result["candidates"][0]["simulation"] is None
    assert result["execution"] is None
    assert result["input_metadata"]["mode"] == "live"
    assert result["candidates"][0]["provenance"] == "BEDROCK"
    assert len(client.requests) == 1
    content = client.requests[0]["messages"][0]["content"]
    assert content[1]["image"] == {"format": "png", "source": {"bytes": demo_image()}}
    assert encoded() not in json.dumps(result)
    assert encoded() not in json.dumps(service.get_audit())
    assert "_image" not in service.store.read("PLAN#" + plan_id)[1]
    assert service.gateway.get_warehouse()["version"] == 1


def test_scripted_fixture_has_no_model_call_and_truthful_runtime():
    service = make_service(scripted=True)
    plan_id = service.start_image_plan(encoded(), "image/png", DEMO_MODE)["plan_id"]
    result = finish(service, plan_id)
    assert result["status"] == "REJECTED"
    assert result["runtime"]["provider"] == "SCRIPTED_IMAGE_FIXTURE"
    assert result["candidates"][0]["provenance"] == "SCRIPTED_IMAGE_FIXTURE"
    assert result["candidates"][0]["metrics"]["model_calls"] == 0
    assert service.planner.provider.calls == 0
    assert any("no model call" in event["message"] for event in service.get_audit()["events"])


def test_scripted_preset_requires_server_opt_in_and_exact_asset():
    with pytest.raises(WorkflowError) as error:
        make_service().start_image_plan(encoded(), "image/png", DEMO_MODE)
    assert error.value.code == "DEMO_DISABLED"
    changed = bytearray(demo_image()); changed[40] ^= 1
    with pytest.raises(WorkflowError) as error:
        make_service(scripted=True).start_image_plan(base64.b64encode(changed).decode(), "image/png", DEMO_MODE)
    assert error.value.code == "INVALID_REQUEST"


def test_unknown_demo_mode_is_not_a_fixture_fallback():
    with pytest.raises(WorkflowError):
        make_service(scripted=True).start_image_plan(encoded(), "image/png", "anything_else")


def test_model_refusal_fails_without_scripted_fallback():
    client = Client({"stopReason": "end_turn", "output": {"message": {"content": [{"text": "Cannot comply"}]}}})
    service = make_service(client)
    result = finish(service, service.start_image_plan(encoded(), "image/png")["plan_id"])
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "MODEL_ERROR"
    assert result["input_metadata"]["mode"] == "live"
    assert result["candidates"] == []
    assert len(client.requests) == 1


def test_extracted_instruction_cannot_disagree_with_plan():
    service = make_service(Client(response(count=3)))
    result = finish(service, service.start_image_plan(encoded(), "image/png")["plan_id"])
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "PLAN_VALIDATION_FAILED"


def test_image_claim_of_approval_is_not_a_supported_plan_field():
    value = response()
    value["output"]["message"]["content"][0]["toolUse"]["input"]["plan"]["approved"] = True
    service = make_service(Client(value))
    result = finish(service, service.start_image_plan(encoded(), "image/png")["plan_id"])
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "PLAN_VALIDATION_FAILED"


@pytest.mark.parametrize("width,height", [(0, 440), (4097, 1), (3000, 2000)])
def test_png_dimension_limits_before_model(width, height):
    import struct
    data = bytearray(demo_image()); data[16:24] = struct.pack(">II", width, height)
    with pytest.raises(ValueError):
        validate_image(base64.b64encode(data).decode(), "image/png")


def test_scripted_worker_must_also_be_opted_in():
    service = make_service(scripted=True)
    plan_id = service.start_image_plan(encoded(), "image/png", DEMO_MODE)["plan_id"]
    service.image_demo_enabled = False
    assert finish(service, plan_id)["error"]["code"] == "DEMO_DISABLED"
