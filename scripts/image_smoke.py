"""One real image/model call and live read-only authorization. Author: Tishneet.

Does not submit or execute a workflow. No inventory mutation is performed.
This probes untrusted instruction extraction, not general injection resistance.
"""
import argparse
import base64
import json
import os

import boto3
from botocore.config import Config

from backend.ai.image_input import demo_image, validate_image
from backend.ai.intent import parse_instruction, check_intent
from backend.ai.providers import BedrockProvider
from backend.ai.validation import validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    config = Config(connect_timeout=5, read_timeout=45, retries={"total_max_attempts": 1})
    # Explicit profile probe must not inherit a personal Bedrock bearer token.
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    if session.client("sts", config=config).get_caller_identity()["Account"] != "737876441172":
        raise SystemExit("Unexpected AWS account; no probe performed.")
    client = session.client("lambda", config=config)
    def invoke(name, payload):
        response = client.invoke(FunctionName=name, Payload=json.dumps(payload).encode())
        if response.get("FunctionError"):
            raise ValueError("Trusted read/authorization function failed")
        return json.loads(response["Payload"].read())
    before = invoke("sentinel-data-warehouse", {})
    provider = BedrockProvider(session.client("bedrock-runtime", config=config), "amazon.nova-pro-v1:0", True)
    image = validate_image(base64.b64encode(demo_image()).decode(), "image/png")
    extracted = provider.generate_image(image, before)
    plan = extracted["plan"]
    try:
        valid = validate_plan(plan)["valid"] and check_intent(plan, parse_instruction(extracted["instruction"]))["valid"]
    except ValueError:
        valid = False
    if not valid:
        print(json.dumps({"validation_passed": False, "workflow_submitted": False,
                          "inventory_operations": 0,
                          "extracted_instruction": extracted["instruction"], "plan": plan}, indent=2))
        return 1
    authorization = invoke("sentinel-security-authorize", {"plan": plan})
    after = invoke("sentinel-data-warehouse", {})
    report = {"provider": "BEDROCK", "model_id": provider.model_id, "region": "us-east-1",
              "image_sha256": image["sha256"], "extracted_instruction": extracted["instruction"],
              "plan": plan, "validation_passed": valid, "authorization": authorization,
              "warehouse_unchanged": before == after, "inventory_operations": 0,
              "workflow_submitted": False, "metrics": provider.metrics,
              "scope": "Untrusted image instruction extraction and existing authorization only"}
    print(json.dumps(report, indent=2))
    return 0 if authorization.get("allowed") is False and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
