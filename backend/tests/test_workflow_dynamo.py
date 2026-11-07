"""DynamoDB-backed assembly acceptance with an in-process AWS emulator.

Author: Tishneet

These checks exercise boto3 request shapes and persisted workflow state through
moto; they are not evidence of a live AWS deployment or DynamoDB Local run.
"""

import unittest

from backend.ai.planner import Planner
from backend.ai.providers import FixtureProvider
from backend.workflows.errors import WorkflowError
from backend.workflows.fixtures import FixtureGateway
from backend.workflows.service import WorkflowService
from backend.workflows.store import DynamoStore
from backend.tests.test_workflow import D1, D2, drive

try:
    import boto3
    from moto import mock_aws
except ImportError:
    boto3 = None
    mock_aws = None


@unittest.skipUnless(mock_aws is not None, "moto and boto3 are not installed")
class DynamoWorkflowAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        self.addCleanup(self.aws.stop)
        self.client = boto3.client("dynamodb", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
        self.client.create_table(TableName="workflows", BillingMode="PAY_PER_REQUEST",
                                 KeySchema=[{"AttributeName": "record_id", "KeyType": "HASH"}],
                                 AttributeDefinitions=[{"AttributeName": "record_id", "AttributeType": "S"}])
        self.now = [1800000000.0]

    def make_service(self):
        store = DynamoStore("workflows", client=self.client)
        return WorkflowService(store, Planner(FixtureProvider()), FixtureGateway(store), clock=lambda: self.now[0])

    def counts(self, service):
        warehouse = service.gateway.get_warehouse()
        return tuple(warehouse["zones"][zone]["inventory"] for zone in "ABC") + (warehouse["version"],)

    def test_pending_approval_and_committed_result_survive_service_recreation(self):
        first = self.make_service()
        d1_id = first.start_plan(D1)["plan_id"]
        self.assertEqual(drive(first, d1_id)["status"], "COMPLETED")
        d2_id = first.start_plan(D2)["plan_id"]
        pending = drive(first, d2_id)
        self.assertEqual(self.counts(first), (17, 8, 8, 2))
        second = self.make_service()
        self.assertEqual(second.get_plan_status(d2_id), pending)
        second.record_approval(pending["approval"]["approval_id"], "APPROVED", "admin-test")
        self.assertEqual(drive(second, d2_id)["status"], "COMPLETED")
        third = self.make_service()
        self.assertEqual(third.get_plan_status(d2_id)["status"], "COMPLETED")
        self.assertEqual(self.counts(third), (12, 10, 11, 3))
        self.assertFalse(third.tick(d2_id))
        self.assertEqual(self.counts(third), (12, 10, 11, 3))

    def test_two_services_reject_stale_state(self):
        first, second = self.make_service(), self.make_service()
        first_id = first.start_plan(D1)["plan_id"]
        second_id = second.start_plan(D1)["plan_id"]
        drive(first, first_id)
        loser = drive(second, second_id)
        self.assertEqual(loser["status"], "FAILED")
        self.assertEqual(loser["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(self.counts(second), (17, 8, 8, 2))

    def test_restart_does_not_extend_approval_deadline(self):
        first = self.make_service()
        plan_id = first.start_plan(D2)["plan_id"]
        before = drive(first, plan_id)
        self.now[0] += 600
        second = self.make_service()
        with self.assertRaises(WorkflowError) as error:
            second.record_approval(before["approval"]["approval_id"], "APPROVED", "admin-test")
        self.assertEqual(error.exception.code, "APPROVAL_EXPIRED")
        self.assertEqual(second.get_plan_status(plan_id)["status"], "EXPIRED")
        self.assertEqual(self.counts(second), (20, 8, 5, 1))


if __name__ == "__main__":
    unittest.main()
