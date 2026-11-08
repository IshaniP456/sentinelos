"""Versioned document stores for workflow coordination.

Author: Tishneet

``list`` uses a paginated, filtered scan in DynamoDB. It is intended for the
bounded single-warehouse demo, not production queue discovery. Replace it with
an indexed work queue before increasing scale. Payloads are JSON strings so
Python integers and floats round-trip without DynamoDB Decimal conversions.
"""

import copy
import json
import os
import threading


class Conflict(Exception):
    """The document version changed; the caller must reload before retrying."""


def _validate(key, value, expected_version):
    if not isinstance(key, str) or not key:
        raise ValueError("key must be a nonempty string")
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("expected_version must be a nonnegative integer")
    if not isinstance(value, dict):
        raise ValueError("value must be a JSON document object")
    # Validate before any transaction writes. Forbid nonstandard NaN/Infinity.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _mutations(mutations):
    entries = list(mutations)
    if len(entries) > 100:
        raise ValueError("transactions support at most 100 documents")
    checked = []
    seen = set()
    for key, value, expected in entries:
        payload = _validate(key, value, expected)
        if key in seen:
            raise ValueError("transaction keys must be unique")
        seen.add(key)
        checked.append((key, payload, expected))
    return checked


def _conditional_failure(error):
    response = getattr(error, "response", {})
    code = response.get("Error", {}).get("Code")
    if code == "ConditionalCheckFailedException":
        return True
    if code == "TransactionCanceledException":
        reasons = response.get("CancellationReasons", [])
        # Do not turn throttling, bad expressions, etc. into retryable CAS loss.
        codes = [reason.get("Code", "None") for reason in reasons]
        return "ConditionalCheckFailed" in codes and all(
            reason in ("None", "ConditionalCheckFailed") for reason in codes
        )
    return False


class MemoryStore:
    """Thread-safe contract double; durable operation requires DynamoStore."""

    def __init__(self):
        self._records = {}
        self._lock = threading.RLock()

    def read(self, key):
        with self._lock:
            return copy.deepcopy(self._records.get(key, (0, None)))

    def write(self, key, value, expected_version):
        self.transact([(key, value, expected_version)])
        return expected_version + 1

    def transact(self, mutations):
        checked = _mutations(mutations)
        with self._lock:
            for key, _, expected in checked:
                current = self._records.get(key, (0, None))[0]
                if current != expected:
                    raise Conflict("document version changed: " + key)
            for key, payload, expected in checked:
                self._records[key] = (expected + 1, json.loads(payload))

    def list(self, prefix):
        if not isinstance(prefix, str):
            raise ValueError("prefix must be a string")
        with self._lock:
            return [(key, version, copy.deepcopy(value))
                    for key, (version, value) in sorted(self._records.items())
                    if key.startswith(prefix)]


class DynamoStore:
    """Low-level DynamoDB CAS store, injectable for AWS-free tests.

    ``create_table`` is deliberately restricted to explicit local endpoints.
    AWS tables must be provisioned by the deployment template instead.
    """

    def __init__(self, table_name="sentinel_workflow", client=None,
                 endpoint_url=None, region_name=None):
        self.table_name = table_name
        self.endpoint_url = endpoint_url or os.environ.get("DYNAMODB_ENDPOINT_URL")
        if client is None:
            import boto3
            kwargs = {"region_name": region_name or os.environ.get("AWS_REGION", "us-east-1")}
            if self.endpoint_url:
                kwargs.update(endpoint_url=self.endpoint_url,
                              aws_access_key_id="local", aws_secret_access_key="local")
            client = boto3.client("dynamodb", **kwargs)
        self.client = client

    def create_table(self):
        """Idempotently provision and wait for a DynamoDB Local demo table."""
        if not self.endpoint_url:
            raise ValueError("table creation requires an explicit DynamoDB Local endpoint")
        from urllib.parse import urlparse
        host = urlparse(self.endpoint_url).hostname
        if host not in ("localhost", "127.0.0.1", "::1", "dynamodb", "dynamodb-local"):
            raise ValueError("automatic table creation is restricted to local endpoints")
        try:
            self.client.create_table(
                TableName=self.table_name,
                KeySchema=[{"AttributeName": "record_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "record_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ResourceInUseException":
                raise
        self.client.get_waiter("table_exists").wait(TableName=self.table_name)

    def read(self, key):
        result = self.client.get_item(
            TableName=self.table_name, Key={"record_id": {"S": key}}, ConsistentRead=True)
        item = result.get("Item")
        if not item:
            return 0, None
        return int(item["version"]["N"]), json.loads(item["payload"]["S"])

    @staticmethod
    def _put(table, key, payload, expected):
        args = {
            "TableName": table,
            "Item": {"record_id": {"S": key}, "version": {"N": str(expected + 1)},
                     "payload": {"S": payload}},
            "ExpressionAttributeNames": {"#version": "version"} if expected else {"#id": "record_id"},
            "ConditionExpression": "#version = :expected" if expected else "attribute_not_exists(#id)",
        }
        if expected:
            args["ExpressionAttributeValues"] = {":expected": {"N": str(expected)}}
        return args

    def write(self, key, value, expected_version):
        payload = _validate(key, value, expected_version)
        try:
            self.client.put_item(**self._put(self.table_name, key, payload, expected_version))
        except Exception as error:
            if _conditional_failure(error):
                raise Conflict("document version changed: " + key) from error
            raise
        return expected_version + 1

    def transact(self, mutations):
        checked = _mutations(mutations)
        if not checked:
            return
        writes = [{"Put": self._put(self.table_name, key, payload, expected)}
                  for key, payload, expected in checked]
        try:
            self.client.transact_write_items(TransactItems=writes)
        except Exception as error:
            if _conditional_failure(error):
                raise Conflict("transaction document version changed") from error
            raise

    def list(self, prefix):
        if not isinstance(prefix, str):
            raise ValueError("prefix must be a string")
        args = {
            "TableName": self.table_name, "ConsistentRead": True, "Limit": 100,
            "FilterExpression": "begins_with(#id, :prefix)",
            "ExpressionAttributeNames": {"#id": "record_id"},
            "ExpressionAttributeValues": {":prefix": {"S": prefix}},
        }
        records = []
        while True:
            page = self.client.scan(**args)
            records.extend((item["record_id"]["S"], int(item["version"]["N"]),
                            json.loads(item["payload"]["S"])) for item in page.get("Items", []))
            last = page.get("LastEvaluatedKey")
            if not last:
                return sorted(records, key=lambda entry: entry[0])
            args["ExclusiveStartKey"] = last
