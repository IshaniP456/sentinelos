"""DynamoDB request/error tests and optional DynamoDB Local persistence tests.

Author: Tishneet

Set DYNAMODB_ENDPOINT_URL to opt into the actual service integration tests.
Those tests create an isolated table and never use AWS account credentials.
"""

import json
import os
import unittest
import uuid

from backend.workflows.store import Conflict, DynamoStore


class ServiceError(Exception):
    def __init__(self, code, reasons=None):
        self.response = {"Error": {"Code": code}}
        if reasons is not None:
            self.response["CancellationReasons"] = [{"Code": reason} for reason in reasons]


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.error = None

    def _call(self, name, kwargs):
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0) if self.responses else {}

    def put_item(self, **kwargs):
        return self._call("put_item", kwargs)

    def get_item(self, **kwargs):
        return self._call("get_item", kwargs)

    def transact_write_items(self, **kwargs):
        return self._call("transact_write_items", kwargs)

    def scan(self, **kwargs):
        return self._call("scan", kwargs)


def item(key, version, value):
    return {"record_id": {"S": key}, "version": {"N": str(version)},
            "payload": {"S": json.dumps(value)}}


class DynamoRequestTests(unittest.TestCase):
    def setUp(self):
        self.client = RecordingClient()
        self.store = DynamoStore("test-workflows", client=self.client)

    def test_strong_read_and_json_round_trip(self):
        self.assertEqual(self.store.read("PLAN#1"), (0, None))
        self.assertTrue(self.client.calls[-1][1]["ConsistentRead"])
        self.client.responses = [{"Item": item("PLAN#1", 2, {"n": 3, "x": 1.5})}]
        self.assertEqual(self.store.read("PLAN#1"), (2, {"n": 3, "x": 1.5}))

    def test_create_and_update_have_different_cas_conditions(self):
        self.assertEqual(self.store.write("PLAN#1", {"status": "PLANNING"}, 0), 1)
        new = self.client.calls[-1][1]
        self.assertEqual(new["ConditionExpression"], "attribute_not_exists(#id)")
        self.assertNotIn("ExpressionAttributeValues", new)
        self.store.write("PLAN#1", {}, 1)
        update = self.client.calls[-1][1]
        self.assertEqual(update["ConditionExpression"], "#version = :expected")
        self.assertEqual(update["ExpressionAttributeValues"], {":expected": {"N": "1"}})
        self.assertEqual(update["Item"]["version"], {"N": "2"})

    def test_atomic_transaction_contains_individual_conditions(self):
        self.store.transact([("WORLD", {"version": 2}, 1), ("EXEC#1", {"done": True}, 0)])
        name, kwargs = self.client.calls[-1]
        self.assertEqual(name, "transact_write_items")
        writes = kwargs["TransactItems"]
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0]["Put"]["ExpressionAttributeValues"][":expected"], {"N": "1"})
        self.assertEqual(writes[1]["Put"]["ConditionExpression"], "attribute_not_exists(#id)")

    def test_conditional_errors_only_become_conflicts(self):
        self.client.error = ServiceError("ConditionalCheckFailedException")
        with self.assertRaises(Conflict):
            self.store.write("PLAN#1", {}, 0)
        self.client.error = ServiceError("TransactionCanceledException", ["None", "ConditionalCheckFailed"])
        with self.assertRaises(Conflict):
            self.store.transact([("PLAN#1", {}, 0)])
        for error in [ServiceError("ProvisionedThroughputExceededException"),
                      ServiceError("TransactionCanceledException"),
                      ServiceError("TransactionCanceledException", ["ConditionalCheckFailed", "ValidationError"])]:
            self.client.error = error
            with self.subTest(error=error.response), self.assertRaises(ServiceError):
                self.store.transact([("PLAN#1", {}, 0)])

    def test_paginated_scan_follows_empty_filtered_pages(self):
        cursor = {"record_id": {"S": "OTHER"}}
        self.client.responses = [
            {"Items": [], "LastEvaluatedKey": cursor},
            {"Items": [item("PLAN#2", 1, {"status": "FAILED"}), item("PLAN#1", 2, {})]},
        ]
        self.assertEqual(self.store.list("PLAN#"), [("PLAN#1", 2, {}), ("PLAN#2", 1, {"status": "FAILED"})])
        self.assertEqual(self.client.calls[-1][1]["ExclusiveStartKey"], cursor)
        self.assertTrue(self.client.calls[-1][1]["ConsistentRead"])

    def test_transaction_input_rejected_before_network(self):
        for changes in [[("K", {}, 0), ("K", {}, 0)], [(str(n), {}, 0) for n in range(101)]]:
            with self.assertRaises(ValueError):
                self.store.transact(changes)
        self.store.transact([])
        self.assertEqual(self.client.calls, [])

    def test_table_creation_is_not_permitted_on_aws(self):
        # The unit contract explicitly models AWS even when Compose supplies a
        # local endpoint to the separate integration tests.
        self.store.endpoint_url = None
        with self.assertRaises(ValueError):
            self.store.create_table()
        self.store.endpoint_url = "https://dynamodb.us-east-1.amazonaws.com"
        with self.assertRaises(ValueError):
            self.store.create_table()


@unittest.skipUnless(os.environ.get("DYNAMODB_ENDPOINT_URL"), "DynamoDB Local endpoint not configured")
class DynamoLocalIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            import boto3
        except ImportError:
            self.skipTest("boto3 is not installed")
        self.name = "sentinel-test-" + uuid.uuid4().hex
        self.store = DynamoStore(self.name, endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"])
        self.store.create_table()
        self.addCleanup(lambda: self.store.client.delete_table(TableName=self.name))

    def test_durable_recreation_and_atomic_conflict(self):
        self.store.write("PLAN#1", {"status": "AWAITING_APPROVAL"}, 0)
        second = DynamoStore(self.name, endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"])
        self.assertEqual(second.read("PLAN#1"), (1, {"status": "AWAITING_APPROVAL"}))
        with self.assertRaises(Conflict):
            second.transact([("EXEC#1", {"done": True}, 0), ("PLAN#1", {}, 0)])
        self.assertEqual(second.read("EXEC#1"), (0, None))
        second.transact([("EXEC#1", {"done": True}, 0), ("PLAN#1", {"status": "COMPLETED"}, 1)])
        self.assertEqual(self.store.list("PLAN#"), [("PLAN#1", 2, {"status": "COMPLETED"})])


if __name__ == "__main__":
    unittest.main()
