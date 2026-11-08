"""Mariam gateway compatibility and reset-race checks. Author: Tishneet.

These contract doubles do not import or replace Mariam's simulator/API modules.
The complete workflow is checked separately in a temporary integration checkout.
"""
import copy
import json
from pathlib import Path
import re
import unittest

import yaml

from backend.ai.planner import Planner
from backend.ai.providers import FixtureProvider
from backend.ai.validation import fingerprint
from backend.workflows.errors import WorkflowError
from backend.workflows.gateway_contracts import NO_COMMIT_ERRORS, normalize_run_id
from backend.workflows.service import WorkflowService
from backend.workflows.store import MemoryStore

SEED = {"warehouse_id": "demo-warehouse", "version": 1,
        "zones": {"A": {"inventory": 20, "capacity": 30},
                  "B": {"inventory": 8, "capacity": 10},
                  "C": {"inventory": 5, "capacity": 20}}, "restricted_zones": ["HAZMAT"]}
GOAL = "Move five packages from Zone A to Zone C."


class GatewayRefusal(Exception):
    """Contract double for Mariam's exception; no owner-source import required."""
    def __init__(self, code, no_commit, retryable=False):
        super().__init__("private-signing-or-transport-detail")
        self.code, self.no_commit, self.retryable = code, no_commit, retryable


class GatewayDouble:
    name = "CONTRACT_DOUBLE"

    def __init__(self):
        self.run_id = "run-original"
        self.reset_calls = []
        self.execute_calls = []
        self.on_reset = None
        self.execution_result = None
        self.dictionary_run_id = False

    def get_run_id(self):
        return {"run_id": self.run_id} if self.dictionary_run_id else self.run_id

    def get_warehouse(self):
        return copy.deepcopy(SEED)

    def reset_demo(self, control_version, control, admin):
        self.reset_calls.append((control_version, control, admin))
        if self.on_reset:
            return self.on_reset(control_version, control, admin)
        self.run_id = "run-after-reset"
        return self.get_warehouse()

    def authorize_plan(self, plan):
        return {"allowed": True, "decisions": [
            {"action_index": i, "allowed": True, "reason_code": "POLICY_ALLOWED"}
            for i, _ in enumerate(plan["actions"])]}

    def simulate_plan(self, plan, warehouse):
        # A predetermined successful projection for this test's one supported
        # scenario, not another implementation of Mariam's simulator.
        return {"passed": True, "warehouse_version": warehouse["version"],
                "reason": None, "violations": [], "projected_state": copy.deepcopy(warehouse["zones"])}

    def execute_plan(self, **kwargs):
        self.execute_calls.append(copy.deepcopy(kwargs))
        if self.execution_result is not None:
            return copy.deepcopy(self.execution_result)
        warehouse = self.get_warehouse()
        warehouse["version"] = kwargs["warehouse_version"] + 1
        return {"executed": True, "status": "COMPLETED", "plan_id": kwargs["plan_id"],
                "revision": kwargs["revision"], "warehouse_version_before": kwargs["warehouse_version"],
                "warehouse_version_after": warehouse["version"], "warehouse": warehouse}


class GatewayContractTests(unittest.TestCase):
    def setUp(self):
        self.now = [1800000000.0]
        self.store = MemoryStore()
        self.gateway = GatewayDouble()
        self.service = self.make_service()

    def make_service(self):
        return WorkflowService(self.store, Planner(FixtureProvider()), self.gateway, clock=lambda: self.now[0])

    def assert_error(self, code, operation):
        with self.assertRaises(WorkflowError) as error:
            operation()
        self.assertEqual(error.exception.code, code)
        return error.exception

    def approval_ready(self):
        plan_id = self.service.start_plan(GOAL)["plan_id"]
        for _ in range(10):
            self.service.tick(plan_id)
            status = self.service.get_plan_status(plan_id)
            if status["status"] == "AWAITING_APPROVAL":
                self.service.record_approval(status["approval"]["approval_id"], "APPROVED", "verified-admin")
                return plan_id
        self.fail("Approval was never requested")

    def finish(self, plan_id):
        for _ in range(10):
            self.service.tick(plan_id)
            status = self.service.get_plan_status(plan_id)
            if status["status"] in {"COMPLETED", "FAILED", "REJECTED"}:
                return status
        return self.service.get_plan_status(plan_id)

    def test_fingerprint_shared_test_vector_hashes_full_plan(self):
        plan = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]}
        self.assertEqual(fingerprint(plan), "4d0939f824e09200aa769aa4a7d6dd719a9c8ce70c2823e0783c34c427fe5f6a")

    def test_run_id_response_is_normalized_to_string(self):
        self.assertEqual(normalize_run_id({"run_id": "example"}), "example")
        for invalid in ({}, {"run_id": None}, {"run_id": " "}, True, None, ""):
            self.assert_error("DEPENDENCY_ERROR", lambda: normalize_run_id(invalid))
        self.gateway.dictionary_run_id = True
        self.assertEqual(self.service.start_plan(GOAL)["status"], "PLANNING")
        self.assertIsInstance(self.store.read("CONTROL")[1]["run_id"], str)

    def test_executor_receives_exact_approval_envelope_and_no_token(self):
        plan_id = self.approval_ready()
        version, record = self.store.read("PLAN#" + plan_id)
        record["approval"]["callback_token"] = "backend-only-secret"
        self.store.write("PLAN#" + plan_id, record, version)
        self.assertEqual(self.finish(plan_id)["status"], "COMPLETED")
        payload = self.gateway.execute_calls[0]["approval"]
        self.assertEqual(set(payload), {"approval_id", "plan_id", "revision", "fingerprint", "warehouse_version",
                                        "run_id", "decision", "admin", "decided_at"})
        self.assertEqual(payload["plan_id"], plan_id)
        self.assertEqual(payload["decision"], "APPROVED")
        self.assertEqual(payload["admin"], "verified-admin")
        self.assertNotIn("backend-only-secret", json.dumps(payload))
        public = self.service.get_plan_status(plan_id)["approval"]
        self.assertEqual(public["status"], "APPROVED")
        self.assertIn("decision_at", public)
        self.assertNotIn("decision", public)

    def test_executor_noncommit_codes_and_retry_flags_are_preserved(self):
        for code in NO_COMMIT_ERRORS:
            for retryable in (False, True):
                with self.subTest(code=code, retryable=retryable):
                    self.setUp()
                    self.gateway.execution_result = {"executed": False, "no_commit": True,
                                                     "error": {"code": code, "message": "secret-debug-value",
                                                               "retryable": retryable}}
                    result = self.finish(self.approval_ready())
                    self.assertEqual(result["error"]["code"], code)
                    self.assertIs(result["error"]["retryable"], retryable)
                    self.assertEqual(result["status"], "REJECTED" if code == "AUTHORIZATION_DENIED" else "FAILED")
                    self.assertNotIn("secret-debug-value", json.dumps(self.service.get_audit()))
                    self.assertNotIn("secret-debug-value", json.dumps(result))
                    self.assertEqual(len(self.gateway.execute_calls), 1)

    def test_bare_error_is_unconfirmed_not_a_terminal_rejection(self):
        self.gateway.execution_result = {"error": {"code": "VERSION_CONFLICT"}}
        result = self.finish(self.approval_ready())
        self.assertEqual(result["status"], "EXECUTING")
        self.assertEqual(result["error"]["code"], "EXECUTION_UNCONFIRMED")

    def test_reset_forwards_admin_after_acquiring_fence_and_blocks_starts(self):
        def remote(version, control, admin):
            current_version, current = self.store.read("CONTROL")
            self.assertEqual(version, current_version)
            self.assertEqual(control, current)
            self.assertEqual(admin, "verified-admin")
            self.assertEqual(control["reset"]["status"], "IN_PROGRESS")
            self.assert_error("RESET_IN_PROGRESS", lambda: self.service.start_plan(GOAL))
            self.assert_error("RESET_IN_PROGRESS", lambda: self.make_service().reset_demo("another-admin"))
            # Mutating the gateway's input must not change stored CONTROL.
            control["reset"] = None
            self.assertIsNotNone(self.store.read("CONTROL")[1]["reset"])
            self.gateway.run_id = "run-new"
            return self.gateway.get_warehouse()
        self.gateway.on_reset = remote
        self.assertEqual(self.service.reset_demo("verified-admin"), SEED)
        control = self.store.read("CONTROL")[1]
        self.assertIsNone(control["reset"])
        self.assertEqual(control["run_id"], "run-new")
        self.assertEqual(control["last_reset"]["admin"], "verified-admin")
        self.assertEqual(len(self.gateway.reset_calls), 1)
        self.assertEqual(self.store.list("PLAN#"), [])
        plan_id = self.service.start_plan(GOAL)["plan_id"]
        self.assertEqual(self.store.read("PLAN#" + plan_id)[1]["_run_id"], "run-new")

    def test_reset_requires_real_admin_before_any_remote_call(self):
        before = self.store.read("CONTROL")
        for admin in (None, "", " ", True, {"admin": "invented"}):
            self.assert_error("FORBIDDEN", lambda: self.service.reset_demo(admin))
        self.assertEqual(self.store.read("CONTROL"), before)
        self.assertEqual(self.gateway.reset_calls, [])

    def test_active_plan_blocks_reset_before_gateway_invocation(self):
        self.service.start_plan(GOAL)
        self.assert_error("VERSION_CONFLICT", lambda: self.service.reset_demo("verified-admin"))
        self.assertEqual(self.gateway.reset_calls, [])

    def test_start_winning_fence_race_prevents_reset(self):
        original_write = self.store.write
        injected = []
        def competing_write(key, value, expected):
            if key == "CONTROL" and value.get("reset") and not injected:
                injected.append(self.service.start_plan(GOAL)["plan_id"])
            return original_write(key, value, expected)
        self.store.write = competing_write
        self.assert_error("VERSION_CONFLICT", lambda: self.service.reset_demo("verified-admin"))
        self.assertEqual(self.gateway.reset_calls, [])
        self.assertEqual(self.store.read("CONTROL")[1]["active"], injected)

    def test_reset_winning_start_race_prevents_old_run_submission(self):
        original_transact = self.store.transact
        injected = []
        def competing_transaction(mutations):
            if any(key.startswith("PLAN#") for key, _, _ in mutations) and not injected:
                injected.append(True)
                self.service.reset_demo("verified-admin")
            return original_transact(mutations)
        self.store.transact = competing_transaction
        plan_id = self.service.start_plan(GOAL)["plan_id"]
        self.assertEqual(len(self.store.list("PLAN#")), 1)
        self.assertEqual(self.store.read("PLAN#" + plan_id)[1]["_run_id"], "run-after-reset")

    def test_lost_reset_ack_stays_fenced_across_restart_and_reconciles_without_retry(self):
        def lost_ack(*args):
            self.gateway.run_id = "run-committed"
            raise TimeoutError("reset-secret-debug")
        self.gateway.on_reset = lost_ack
        error = self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        self.assertNotIn("reset-secret-debug", str(error))
        fence = self.store.read("CONTROL")[1]["reset"]
        self.assertEqual(fence["status"], "UNCONFIRMED")
        self.now[0] += 100000
        recreated = self.make_service()
        self.assert_error("RESET_IN_PROGRESS", lambda: recreated.start_plan(GOAL))
        self.assert_error("RESET_IN_PROGRESS", lambda: recreated.reset_demo("verified-admin"))
        result = recreated.reconcile_reset(fence["reset_id"], "verified-admin")
        self.assertEqual(result, SEED)
        self.assertEqual(len(self.gateway.reset_calls), 1)
        self.assertEqual(recreated.reconcile_reset(fence["reset_id"], "verified-admin"), result)
        self.assertIsNone(self.store.read("CONTROL")[1]["reset"])

    def test_unrotated_or_malformed_reset_outcome_never_unfences_automatically(self):
        for response in (SEED, {}, {"error": {"code": "BUSY"}}, None):
            with self.subTest(response=response):
                self.setUp()
                self.gateway.on_reset = lambda *args: copy.deepcopy(response)
                self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
                reset_id = self.store.read("CONTROL")[1]["reset"]["reset_id"]
                self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reconcile_reset(reset_id, "verified-admin"))
                self.assert_error("RESET_IN_PROGRESS", lambda: self.service.start_plan(GOAL))
                self.assertEqual(len(self.gateway.reset_calls), 1)

    def test_unknown_reset_reference_cannot_clear_fence(self):
        self.gateway.on_reset = lambda *args: None
        self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        self.assert_error("RESET_CONFLICT", lambda: self.service.reconcile_reset("other-reset", "verified-admin"))
        self.assertIsNotNone(self.store.read("CONTROL")[1]["reset"])

    def test_reset_commit_with_failed_control_completion_remains_recoverable(self):
        original_write = self.store.write
        def fail_completion(key, value, expected):
            if key == "CONTROL" and value.get("last_reset") and value.get("reset") is None:
                raise OSError("storage-secret-debug")
            return original_write(key, value, expected)
        self.store.write = fail_completion
        error = self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        self.assertNotIn("storage-secret-debug", str(error))
        reset_id = self.store.read("CONTROL")[1]["reset"]["reset_id"]
        self.assert_error("RESET_IN_PROGRESS", lambda: self.service.start_plan(GOAL))
        self.store.write = original_write
        self.assertEqual(self.make_service().reconcile_reset(reset_id, "verified-admin"), SEED)
        self.assertEqual(len(self.gateway.reset_calls), 1)

    def test_workflow_iam_has_only_own_table_and_six_nonadmin_callees(self):
        class TemplateLoader(yaml.SafeLoader):
            pass
        def tagged(loader, tag, node):
            return {tag: loader.construct_scalar(node)}
        TemplateLoader.add_multi_constructor("!", tagged)
        path = Path(__file__).parents[1] / "workflows" / "template.yaml"
        template = yaml.load(path.read_text(), Loader=TemplateLoader)
        table_names = [name for name, resource in template["Resources"].items()
                       if resource["Type"] == "AWS::DynamoDB::Table"]
        self.assertEqual(table_names, ["WorkflowTable"])
        policy = template["Resources"]["WorkflowFunction"]["Properties"]["Policies"][0]["Statement"]
        for statement in policy:
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            self.assertFalse(any(a.startswith(("secretsmanager:", "ssm:", "kms:")) for a in actions))
            if any(a.startswith("dynamodb:") for a in actions):
                self.assertEqual(statement["Resource"], {"GetAtt": "WorkflowTable.Arn"})
        parameter = template["Parameters"]["TrustedFunctionArns"]
        arns = parameter["Default"].split(",")
        self.assertEqual(len(set(arns)), 6)
        self.assertEqual({a.rsplit(":", 1)[1] for a in arns}, {
            "sentinel-data-warehouse", "sentinel-data-agent", "sentinel-data-runid",
            "sentinel-data-execute", "sentinel-data-audit-append", "sentinel-security-authorize"})
        for arn in arns:
            self.assertRegex(arn, parameter["AllowedPattern"])
        for name in ("sentinel-data-revoke", "sentinel-data-reset"):
            self.assertIsNone(re.fullmatch(parameter["AllowedPattern"],
                                          "arn:aws:lambda:us-east-1:737876441172:function:" + name))

    def test_lost_control_completion_ack_returns_confirmed_saved_result(self):
        original_write = self.store.write
        def lost_ack(key, value, expected):
            result = original_write(key, value, expected)
            if key == "CONTROL" and value.get("last_reset") and value.get("reset") is None:
                raise TimeoutError("Reply lost after CONTROL commit")
            return result
        self.store.write = lost_ack
        self.assertEqual(self.service.reset_demo("verified-admin"), SEED)
        self.assertIsNone(self.store.read("CONTROL")[1]["reset"])
        self.assertEqual(len(self.gateway.reset_calls), 1)
        self.assertEqual(self.service.start_plan(GOAL)["status"], "PLANNING")

    def test_reset_response_does_not_expose_gateway_debug_metadata(self):
        def remote(*args):
            self.gateway.run_id = "run-clean"
            response = self.gateway.get_warehouse()
            response["debug"] = "reset-secret-debug"
            response["zones"]["A"]["debug"] = "zone-secret-debug"
            return response
        self.gateway.on_reset = remote
        result = self.service.reset_demo("verified-admin")
        self.assertEqual(result, SEED)
        self.assertNotIn("secret-debug", json.dumps(self.store.read("CONTROL")))

    def test_confirmed_gateway_refusal_clears_only_its_fence_and_preserves_error(self):
        for code, status in (("VERSION_CONFLICT", 409), ("FORBIDDEN", 403), ("NOT_FOUND", 404),
                             ("INVALID_REQUEST", 400), ("INTERNAL_ERROR", 503)):
            with self.subTest(code=code):
                self.setUp()
                def refuse(*args):
                    raise GatewayRefusal(code, True, retryable=code == "VERSION_CONFLICT")
                self.gateway.on_reset = refuse
                error = self.assert_error(code, lambda: self.service.reset_demo("verified-admin"))
                self.assertEqual(error.status, status)
                self.assertEqual(error.retryable, code == "VERSION_CONFLICT")
                self.assertNotIn("private-signing", str(error))
                control = self.store.read("CONTROL")[1]
                self.assertIsNone(control["reset"])
                self.assertEqual(control["run_id"], "run-original")
                self.assertEqual(control["last_reset_refusal"]["code"], code)
                self.assertNotIn("private-signing", json.dumps(control))
                self.assert_error(code, lambda: self.service.reconcile_reset(
                    control["last_reset_refusal"]["reset_id"], "verified-admin"))
                self.assertEqual(self.service.start_plan(GOAL)["status"], "PLANNING")
                self.assertEqual(len(self.gateway.reset_calls), 1)

    def test_ambiguous_gateway_error_keeps_reset_fenced(self):
        for no_commit in (False, None, "true", 1):
            with self.subTest(no_commit=no_commit):
                self.setUp()
                def ambiguous(*args):
                    raise GatewayRefusal("INTERNAL_ERROR", no_commit)
                self.gateway.on_reset = ambiguous
                self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
                self.assertIsNotNone(self.store.read("CONTROL")[1]["reset"])
                self.assert_error("RESET_IN_PROGRESS", lambda: self.service.start_plan(GOAL))

    def test_read_failure_after_success_is_not_mistaken_for_reset_refusal(self):
        original_read = self.gateway.get_run_id
        def reset_then_fail_read(*args):
            self.gateway.run_id = "run-committed"
            def denied_read():
                raise GatewayRefusal("NOT_FOUND", True)
            self.gateway.get_run_id = denied_read
            return self.gateway.get_warehouse()
        self.gateway.on_reset = reset_then_fail_read
        self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        reset_id = self.store.read("CONTROL")[1]["reset"]["reset_id"]
        self.gateway.get_run_id = original_read
        self.assertEqual(self.service.reconcile_reset(reset_id, "verified-admin"), SEED)
        self.assertEqual(len(self.gateway.reset_calls), 1)

    def test_lost_refusal_cursor_ack_does_not_leave_a_phantom_reset(self):
        original_write = self.store.write
        def lost_ack(key, value, expected):
            result = original_write(key, value, expected)
            if key == "CONTROL" and value.get("last_reset_refusal") and value.get("reset") is None:
                raise TimeoutError("Control write reply lost")
            return result
        self.store.write = lost_ack
        def refused(*args):
            raise GatewayRefusal("VERSION_CONFLICT", True, True)
        self.gateway.on_reset = refused
        self.assert_error("VERSION_CONFLICT", lambda: self.service.reset_demo("verified-admin"))
        self.assertIsNone(self.store.read("CONTROL")[1]["reset"])

    def test_refusal_clear_storage_failure_keeps_the_original_fence(self):
        original_write = self.store.write
        def unavailable_write(key, value, expected):
            if key == "CONTROL" and value.get("last_reset_refusal") and value.get("reset") is None:
                raise OSError("Cannot persist refusal completion")
            return original_write(key, value, expected)
        self.store.write = unavailable_write
        def refused(*args):
            raise GatewayRefusal("FORBIDDEN", True)
        self.gateway.on_reset = refused
        self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        self.assertIsNotNone(self.store.read("CONTROL")[1]["reset"])

    def test_old_refusal_cannot_clear_a_newer_reset_fence(self):
        def replace_then_refuse(*args):
            version, control = self.store.read("CONTROL")
            control["reset"]["reset_id"] = "newer-reset"
            self.store.write("CONTROL", control, version)
            raise GatewayRefusal("FORBIDDEN", True)
        self.gateway.on_reset = replace_then_refuse
        self.assert_error("RESET_UNCONFIRMED", lambda: self.service.reset_demo("verified-admin"))
        self.assertEqual(self.store.read("CONTROL")[1]["reset"]["reset_id"], "newer-reset")


if __name__ == "__main__":
    unittest.main()
