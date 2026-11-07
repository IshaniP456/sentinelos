"""AWS orchestration transport and definition checks. Author: Tishneet."""

import copy
import json
from pathlib import Path
import unittest

from backend.workflows.aws import (
    AwsWorkflowBackend, WorkflowStartError, callback_sender, handler,
)

try:
    import yaml
except ImportError:
    yaml = None


class FakeService:
    def __init__(self):
        self.calls = []
        self.status = "PLANNING"

    def start_plan(self, instruction):
        self.calls.append(("start", instruction))
        return {"plan_id": "plan-123", "status": "PLANNING"}

    def get_plan_status(self, plan_id):
        return {"plan_id": plan_id, "status": self.status}

    def tick(self, **kwargs):
        self.calls.append(("tick", kwargs))
        self.status = "VALIDATING"
        return True

    def register_callback(self, plan_id, token):
        self.calls.append(("register", plan_id, token))

    def expire_approval(self, plan_id):
        self.calls.append(("expire", plan_id))
        self.status = "EXPIRED"

    def fail_plan(self, plan_id, code, message):
        self.calls.append(("fail", plan_id, code, message))
        if self.status != "COMPLETED":
            self.status = "FAILED"


class FakeClient:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def start_execution(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"executionArn": "arn:example:execution"}

    def send_task_success(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {}


class RejectedStart(Exception):
    response = {"Error": {"Code": "AccessDeniedException"}}


class AwsDispatchTests(unittest.TestCase):
    def test_sam_source_is_repository_and_architecture_matches_build(self):
        template = Path(__file__).parents[1] / "workflows" / "template.yaml"
        text = template.read_text()
        self.assertIn("CodeUri: ../..", text)
        self.assertEqual((template.parent / "../..").resolve(), Path(__file__).resolve().parents[2])
        self.assertIn("Architectures: [arm64]", text)
        self.assertIn("BuildMethod: makefile", text)

    def test_advance_is_one_persisted_step(self):
        service = FakeService()
        event = {"operation": "advance", "plan_id": "p1"}
        before = copy.deepcopy(event)
        self.assertEqual(handler(event, service=service)["status"], "VALIDATING")
        self.assertEqual(service.calls, [("tick", {"plan_id": "p1", "owner": "stepfunctions"})])
        self.assertEqual(event, before)

    def test_status_never_advances(self):
        service = FakeService()
        handler({"operation": "status", "plan_id": "p1"}, service=service)
        self.assertEqual(service.calls, [])

    def test_registration_does_not_return_token(self):
        service = FakeService()
        result = handler({"operation": "register_approval", "plan_id": "p1",
                          "task_token": "secret-token"}, service=service)
        self.assertEqual(service.calls, [("register", "p1", "secret-token")])
        self.assertNotIn("secret-token", json.dumps(result))

    def test_registration_requires_token(self):
        with self.assertRaises(ValueError):
            handler({"operation": "register_approval", "plan_id": "p1"}, service=FakeService())

    def test_expiry_persists_and_reads(self):
        service = FakeService()
        result = handler({"operation": "expire", "plan_id": "p1"}, service=service)
        self.assertEqual(result["status"], "EXPIRED")
        self.assertEqual(service.calls, [("expire", "p1")])

    def test_failure_does_not_echo_sensitive_exception_data(self):
        service = FakeService()
        result = handler({"operation": "fail", "plan_id": "p1",
                          "transport_error": {"Cause": "secret-token"}}, service=service)
        self.assertEqual(result["status"], "FAILED")
        self.assertNotIn("secret-token", repr(service.calls))

    def test_failure_does_not_relabel_completed_execution(self):
        service = FakeService()
        service.status = "COMPLETED"
        self.assertEqual(handler({"operation": "fail", "plan_id": "p1"}, service=service)["status"],
                         "COMPLETED")

    def test_unknown_operation_and_missing_id_fail(self):
        for event in ({"operation": "execute_anything"}, {"operation": "status"}, []):
            with self.subTest(event=event), self.assertRaises(ValueError):
                handler(event, service=FakeService())

    def test_callback_payload_contains_only_decision(self):
        client = FakeClient()
        for decision in ("APPROVED", "DENIED"):
            callback_sender(client)("secret", decision)
            self.assertEqual(client.calls[-1]["taskToken"], "secret")
            self.assertEqual(json.loads(client.calls[-1]["output"]), {"decision": decision})

    def test_callback_errors_propagate_without_false_confirmation(self):
        with self.assertRaises(RuntimeError):
            callback_sender(FakeClient(RuntimeError("timeout")))("secret", "APPROVED")
        with self.assertRaises(ValueError):
            callback_sender(FakeClient())("secret", "ALLOW")

    def test_start_name_and_input_bind_same_plan(self):
        client = FakeClient()
        service = FakeService()
        backend = AwsWorkflowBackend(service, "arn:state-machine", client)
        result = backend.start_plan("move three")
        backend.start_existing(result["plan_id"])
        self.assertEqual(client.calls[0], client.calls[1])
        self.assertEqual(json.loads(client.calls[0]["input"]), {"plan_id": "plan-123"})
        self.assertEqual(client.calls[0]["name"], "plan-123")
        self.assertEqual(len([c for c in service.calls if c[0] == "start"]), 1)

    def test_rejected_start_fails_durably(self):
        service = FakeService()
        backend = AwsWorkflowBackend(service, "arn:state-machine", FakeClient(RejectedStart()))
        with self.assertRaises(WorkflowStartError) as caught:
            backend.start_plan("move three")
        self.assertFalse(caught.exception.ambiguous)
        self.assertEqual(service.status, "FAILED")

    def test_ambiguous_start_retains_existing_plan(self):
        service = FakeService()
        backend = AwsWorkflowBackend(service, "arn:state-machine", FakeClient(TimeoutError()))
        with self.assertRaises(WorkflowStartError) as caught:
            backend.start_plan("move three")
        self.assertTrue(caught.exception.ambiguous)
        self.assertEqual(caught.exception.plan_id, "plan-123")
        self.assertEqual(service.status, "PLANNING")

    def test_no_restart_after_progress(self):
        service = FakeService()
        service.status = "COMPLETED"
        with self.assertRaises(ValueError):
            AwsWorkflowBackend(service, "arn:state-machine", FakeClient()).start_existing("p1")


class DefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).parents[1] / "workflows" / "statemachine.asl.json"
        cls.definition = json.loads(cls.path.read_text())

    def test_all_states_reachable_and_transitions_valid(self):
        states = self.definition["States"]
        visited = set()

        def visit(name):
            self.assertIn(name, states)
            if name in visited:
                return
            visited.add(name)
            state = states[name]
            targets = [state[k] for k in ("Next", "Default") if k in state]
            targets += [item["Next"] for item in state.get("Choices", [])]
            targets += [item["Next"] for item in state.get("Catch", [])]
            for target in targets:
                visit(target)

        visit(self.definition["StartAt"])
        self.assertEqual(visited, set(states))

    def test_every_state_has_a_path_to_a_terminal(self):
        states = self.definition["States"]

        def reaches_end(name, visited):
            state = states[name]
            if state["Type"] in {"Succeed", "Fail"}:
                return True
            if name in visited:
                return False
            targets = [state[k] for k in ("Next", "Default") if k in state]
            targets += [item["Next"] for item in state.get("Choices", [])]
            targets += [item["Next"] for item in state.get("Catch", [])]
            return any(reaches_end(target, visited | {name}) for target in targets)

        for name in states:
            self.assertTrue(reaches_end(name, set()), name)

    def test_approval_has_callback_and_explicit_timeout(self):
        state = self.definition["States"]["WaitForApproval"]
        self.assertTrue(state["Resource"].endswith(".waitForTaskToken"))
        self.assertEqual(state["TimeoutSeconds"], 600)
        self.assertEqual(state["Parameters"]["Payload"]["task_token.$"], "$$.Task.Token")
        self.assertEqual(state["Catch"][0]["Next"], "ExpireApproval")

    def test_all_tasks_preserve_original_context_and_have_failure_path(self):
        for name, state in self.definition["States"].items():
            if state["Type"] != "Task":
                continue
            self.assertIn("TimeoutSeconds", state, name)
            self.assertIn("Catch", state, name)
            self.assertNotEqual(state.get("ResultPath", "$"), "$", name)

    def test_no_implicit_retry_regenerates_candidates(self):
        for name in ("GeneratePlan", "Replan", "ExecutePlan"):
            self.assertNotIn("Retry", self.definition["States"][name])

    def test_transition_tasks_outlive_function_timeout(self):
        for name, state in self.definition["States"].items():
            if state["Type"] == "Task" and name != "WaitForApproval":
                self.assertGreater(state["TimeoutSeconds"], 75, name)

    def test_only_completed_is_successful(self):
        succeeded = [name for name, state in self.definition["States"].items()
                     if state["Type"] == "Succeed"]
        self.assertEqual(succeeded, ["Completed"])
        self.assertLessEqual(self.definition["TimeoutSeconds"], 1800)


class ServiceTransportIntegrationTests(unittest.TestCase):
    """Actual business service with injected transport, no AWS calls."""

    def setUp(self):
        from backend.ai.planner import Planner
        from backend.ai.providers import FixtureProvider
        from backend.workflows.fixtures import FixtureGateway
        from backend.workflows.service import WorkflowService
        from backend.workflows.store import MemoryStore

        self.client = FakeClient()
        store = MemoryStore()
        self.service = WorkflowService(
            store, Planner(FixtureProvider()), FixtureGateway(store),
            callback_sender=callback_sender(self.client),
        )

    def advance_until_pause(self, plan_id):
        for _ in range(30):
            status = handler({"operation": "status", "plan_id": plan_id}, service=self.service)
            if status["status"] in {"AWAITING_APPROVAL", "COMPLETED", "REJECTED", "FAILED", "EXPIRED"}:
                return status
            handler({"operation": "advance", "plan_id": plan_id}, service=self.service)
        self.fail("Workflow failed to reach a pause within its candidate bound")

    def test_real_low_risk_service_runs_through_transport(self):
        result = self.service.start_plan("Move three packages from Zone A to Zone C.")
        status = self.advance_until_pause(result["plan_id"])
        self.assertEqual(status["status"], "COMPLETED")
        self.assertEqual(status["execution"]["warehouse"]["zones"]["A"]["inventory"], 17)
        self.assertEqual(status["execution"]["warehouse"]["zones"]["C"]["inventory"], 8)
        self.assertEqual(self.client.calls, [])

    def test_real_approval_wait_callback_then_rechecks_execute(self):
        result = self.service.start_plan(
            "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary."
        )
        plan_id = result["plan_id"]
        paused = self.advance_until_pause(plan_id)
        self.assertEqual(paused["status"], "AWAITING_APPROVAL")
        self.assertEqual(len(paused["candidates"]), 2)
        handler({"operation": "register_approval", "plan_id": plan_id,
                 "task_token": "backend-only-token"}, service=self.service)
        approval_id = paused["approval"]["approval_id"]
        self.service.record_approval(approval_id, "APPROVED", "verified-admin")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(json.loads(self.client.calls[0]["output"]), {"decision": "APPROVED"})
        status = self.advance_until_pause(plan_id)
        self.assertEqual(status["status"], "COMPLETED")
        self.assertNotIn("backend-only-token", json.dumps(status))
        self.service.record_approval(approval_id, "APPROVED", "verified-admin")
        self.assertEqual(len(self.client.calls), 1)

    def test_decision_before_callback_registration_is_delivered(self):
        result = self.service.start_plan("Move five packages from Zone A to Zone C.")
        plan_id = result["plan_id"]
        paused = self.advance_until_pause(plan_id)
        self.service.record_approval(paused["approval"]["approval_id"], "APPROVED", "verified-admin")
        self.assertEqual(self.client.calls, [])
        handler({"operation": "register_approval", "plan_id": plan_id,
                 "task_token": "late-registration-token"}, service=self.service)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.advance_until_pause(plan_id)["status"], "COMPLETED")

    def test_denial_before_registration_is_delivered_without_execution(self):
        result = self.service.start_plan("Move five packages from Zone A to Zone C.")
        plan_id = result["plan_id"]
        paused = self.advance_until_pause(plan_id)
        self.service.record_approval(paused["approval"]["approval_id"], "DENIED", "verified-admin")
        handler({"operation": "register_approval", "plan_id": plan_id,
                 "task_token": "late-denied-token"}, service=self.service)
        self.assertEqual(json.loads(self.client.calls[0]["output"]), {"decision": "DENIED"})
        self.assertEqual(self.advance_until_pause(plan_id)["status"], "REJECTED")
        self.assertEqual(self.service.gateway.get_warehouse()["version"], 1)


@unittest.skipIf(yaml is None, "PyYAML is required for static SAM checks")
class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Loader(yaml.SafeLoader):
            pass

        def intrinsic(loader, tag, node):
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
            elif isinstance(node, yaml.SequenceNode):
                value = loader.construct_sequence(node)
            else:
                value = loader.construct_mapping(node)
            return {tag: value}

        Loader.add_multi_constructor("!", intrinsic)
        cls.template = yaml.load(
            (Path(__file__).parents[1] / "workflows" / "template.yaml").read_text(),
            Loader=Loader,
        )

    def test_standard_runtime_and_definition(self):
        resources = self.template["Resources"]
        fn = resources["WorkflowFunction"]["Properties"]
        machine = resources["WorkflowStateMachine"]["Properties"]
        self.assertEqual(fn["Runtime"], "python3.12")
        self.assertEqual(fn["Handler"], "backend.workflows.aws.handler")
        self.assertEqual(machine["Type"], "STANDARD")
        self.assertEqual(machine["DefinitionUri"], "statemachine.asl.json")

    def test_no_function_to_state_machine_dependency_cycle(self):
        env = self.template["Resources"]["WorkflowFunction"]["Properties"]["Environment"]["Variables"]
        self.assertNotIn("SENTINEL_STATE_MACHINE_ARN", env)
        self.assertEqual(env["SENTINEL_MODEL_PROVIDER"], "bedrock")
        self.assertNotIn("SENTINEL_AUTH_MODE", env)

    def test_only_callback_policy_has_wildcard_resource(self):
        policies = self.template["Resources"]["WorkflowFunction"]["Properties"]["Policies"]
        statements = policies[0]["Statement"]
        wildcard = [item for item in statements if item["Resource"] == "*"]
        self.assertEqual(len(wildcard), 1)
        self.assertEqual(wildcard[0]["Action"], "states:SendTaskSuccess")

    def test_model_and_trusted_adapters_are_explicit_parameters(self):
        parameters = self.template["Parameters"]
        for key in ("BedrockModelId", "BedrockModelArn", "BedrockUnderlyingModelArns",
                    "TrustedAdapterModule", "TrustedFunctionArns"):
            self.assertIn(key, parameters)
            self.assertNotIn("Default", parameters[key])


if __name__ == "__main__":
    unittest.main()
