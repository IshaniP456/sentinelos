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


if __name__ == "__main__":
    unittest.main()
