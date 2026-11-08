"""HTTP seam tests against Tishneet's actual durable workflow. Author: Tishneet."""
import json
import unittest
from unittest.mock import patch

from backend.ai.planner import Planner
from backend.ai.providers import FixtureProvider
from backend.api import backend_ops, auth
from backend.api.handlers import handler
from backend.api.responses import ApiError
from backend.workflows.api_adapter import WorkflowBackendOps
from backend.workflows.aws import AwsWorkflowBackend
from backend.workflows.fixtures import FixtureGateway
from backend.workflows.service import WorkflowService
from backend.workflows.store import MemoryStore


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        store = MemoryStore()
        self.service = WorkflowService(store, Planner(FixtureProvider()), FixtureGateway(store))
        self.adapter = WorkflowBackendOps(self.service)
        self.singleton = patch.object(backend_ops, "_SINGLETON", self.adapter)
        self.singleton.start()
        self.addCleanup(self.singleton.stop)
        self.authmode = patch.object(auth, "AUTH_MODE", "prod")
        self.authmode.start()
        self.addCleanup(self.authmode.stop)

    def call(self, method, path, body=None, claims=None):
        return handler({"httpMethod": method, "path": path, "body": json.dumps(body) if body is not None else None,
                        "requestContext": {"authorizer": {"jwt": {"claims": claims or {}}}}})

    def test_submit_and_poll_no_side_effects(self):
        response = self.call("POST", "/v1/plans", {"instruction": "Move three packages from A to C."})
        self.assertEqual(response["statusCode"], 202)
        plan_id = json.loads(response["body"])["plan_id"]
        for _ in range(4):
            status = self.call("GET", "/v1/plans/" + plan_id)
            self.assertEqual(json.loads(status["body"])["status"], "PLANNING")
        self.assertEqual(self.service.gateway.get_warehouse()["version"], 1)

    def test_image_adapter_submission_returns_normal_trackable_reference(self):
        import base64
        from backend.ai.image_input import demo_image
        result = self.adapter.start_image_plan(base64.b64encode(demo_image()).decode(), "image/png")
        self.assertEqual(result["status"], "PLANNING")
        status = self.adapter.get_plan_status(result["plan_id"])
        self.assertEqual(status["input_metadata"]["mode"], "live")
        self.assertNotIn("image_b64", status)

    def test_image_start_timeout_preserves_original_reference(self):
        import base64
        from backend.ai.image_input import demo_image
        class TimeoutClient:
            def start_execution(self, **kwargs):
                self.input = kwargs["input"]
                raise TimeoutError("unconfirmed start")
        client = TimeoutClient()
        self.adapter.starter = AwsWorkflowBackend(self.service, "arn:example:machine", client)
        result = self.adapter.start_image_plan(base64.b64encode(demo_image()).decode(), "image/png")
        self.assertFalse(result["start_confirmed"])
        self.assertEqual(json.loads(client.input), {"plan_id": result["plan_id"]})
        self.assertEqual(len(self.service.store.list("PLAN#")), 1)

    def test_invalid_request_standard_error(self):
        response = self.call("POST", "/v1/plans", {"instruction": "Do something safe"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["code"], "INVALID_REQUEST")

    def test_admin_exact_groups_and_http_jwt(self):
        for groups in ("nonadmin", "admin-readonly", "superadmin", ["administrator"], "[]"):
            response = self.call("POST", "/v1/agents/current/revoke", {}, {"sub": "operator", "groups": groups})
            self.assertEqual(response["statusCode"], 403)
        self.assertEqual(self.service.gateway.get_agent()["status"], "ACTIVE")
        response = self.call("POST", "/v1/agents/current/revoke", {}, {"sub": "admin-1", "groups": ["admin"]})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.service.gateway.get_agent()["status"], "REVOKED")

    def test_admin_requires_verified_identity(self):
        self.assertEqual(self.call("POST", "/v1/demo/reset", {}, {"groups": ["admin"]})["statusCode"], 403)

    def test_ambiguous_aws_start_preserves_plan_id(self):
        class TimeoutClient:
            def start_execution(self, **kwargs):
                raise TimeoutError("Reply unavailable")
        self.adapter.starter = AwsWorkflowBackend(self.service, "arn:aws:states:us-east-1:123:stateMachine:demo", TimeoutClient())
        response = self.call("POST", "/v1/plans", {"instruction": "Move three packages from A to C."})
        self.assertEqual(response["statusCode"], 202)
        result = json.loads(response["body"])
        self.assertFalse(result["start_confirmed"])
        self.assertEqual(self.service.get_plan_status(result["plan_id"])["status"], "PLANNING")
        self.assertEqual(len(self.service.store.list("PLAN#")), 1)

    def test_aws_client_initialization_failure_preserves_id(self):
        self.adapter.starter = AwsWorkflowBackend(self.service, "arn:aws:states:us-east-1:123:stateMachine:demo")
        with patch("backend.workflows.aws._sfn_client", side_effect=RuntimeError("Credentials unavailable")):
            response = self.call("POST", "/v1/plans", {"instruction": "Move three packages from A to C."})
        self.assertEqual(response["statusCode"], 202)
        self.assertIn("plan_id", json.loads(response["body"]))

    def test_gateway_admin_refusals_keep_their_http_status_and_do_not_leak_details(self):
        class GatewayError(Exception):
            code = "FORBIDDEN"
            no_commit = True
            retryable = False
        def refuse(admin):
            raise GatewayError("private-signing-detail")
        self.service.gateway.revoke_agent = refuse
        response = self.call("POST", "/v1/agents/current/revoke", {}, {"sub": "admin-1", "groups": ["admin"]})
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(json.loads(response["body"])["error"]["code"], "FORBIDDEN")
        self.assertNotIn("private-signing-detail", response["body"])

    def test_ambiguous_revoke_failure_is_not_presented_as_safe_to_retry(self):
        def lost_ack(admin):
            raise TimeoutError("private-transport-detail")
        self.service.gateway.revoke_agent = lost_ack
        response = self.call("POST", "/v1/agents/current/revoke", {}, {"sub": "admin-1", "groups": ["admin"]})
        self.assertEqual(response["statusCode"], 502)
        error = json.loads(response["body"])["error"]
        self.assertEqual(error["code"], "GATEWAY_UNCONFIRMED")
        self.assertFalse(error["retryable"])
        self.assertNotIn("private-transport-detail", response["body"])


if __name__ == "__main__":
    unittest.main()
