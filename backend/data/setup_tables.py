"""Inspect, and optionally create and seed, the SentinelOS DynamoDB tables.

Default is a dry run: shows the AWS account and Region, which tables exist,
whether their keys match the contract, and what would be created.

    python -m data.setup_tables            # dry run, changes nothing
    python -m data.setup_tables --apply    # create MISSING tables, then seed if empty

Safety rules:
  * Never deletes or modifies an existing table.
  * Never overwrites an existing warehouse or agent record (seed_if_missing).
  * If the shared SAM template will own these tables, do not use --apply;
    CloudFormation cannot adopt tables created outside it.
"""

import argparse
import sys
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from data import dynamo
from data.schema import table_definitions


def _key_summary(definition: dict[str, Any]) -> list[tuple[str, str]]:
    return [(k["AttributeName"], k["KeyType"]) for k in definition["KeySchema"]]


def inspect(client: Any) -> list[dict[str, Any]]:
    """Return one status row per contract table: missing, matches, or mismatch."""
    rows = []
    for definition in table_definitions():
        name = definition["TableName"]
        try:
            table = client.describe_table(TableName=name)["Table"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            rows.append({"table": name, "status": "missing", "definition": definition})
            continue
        actual_keys = _key_summary(table)
        expected_keys = _key_summary(definition)
        expected_indexes = {i["IndexName"] for i in definition.get("GlobalSecondaryIndexes", [])}
        actual_indexes = {i["IndexName"] for i in table.get("GlobalSecondaryIndexes", [])}
        problems = []
        if actual_keys != expected_keys:
            problems.append(f"keys {actual_keys} != expected {expected_keys}")
        if not expected_indexes <= actual_indexes:
            problems.append(f"missing indexes {sorted(expected_indexes - actual_indexes)}")
        rows.append(
            {
                "table": name,
                "status": "mismatch" if problems else "matches",
                "problems": problems,
                "items": table.get("ItemCount"),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="create missing tables and seed them")
    args = parser.parse_args(argv)

    try:
        session = boto3.session.Session()
        identity = session.client("sts").get_caller_identity()
        client = session.client("dynamodb")
        print(f"AWS account: {identity['Account']}")
        print(f"Caller:      {identity['Arn']}")
        print(f"Region:      {session.region_name}")
        rows = inspect(client)
    except (BotoCoreError, ClientError) as exc:
        print(f"Cannot reach AWS: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    for row in rows:
        detail = "; ".join(row.get("problems", [])) or (
            f"{row['items']} items" if row["status"] == "matches" else "would be created"
        )
        print(f"  {row['table']:<22} {row['status']:<9} {detail}")

    if any(r["status"] == "mismatch" for r in rows):
        print("A table exists with a different design. Nothing changed; resolve it with the team.")
        return 1
    missing = [r for r in rows if r["status"] == "missing"]
    if not args.apply:
        print("Dry run only. Re-run with --apply to create missing tables and seed them.")
        return 0

    for row in missing:
        client.create_table(**row["definition"])
        print(f"Creating {row['table']} ...")
    for row in missing:
        client.get_waiter("table_exists").wait(TableName=row["table"])
    dynamo.reset_connection()
    print(f"Seed: {dynamo.seed_if_missing()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
