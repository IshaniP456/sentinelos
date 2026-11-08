"""Read-only deployment identity gate; no resources created. Author: Tishneet."""
import argparse
import json
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ACCOUNT = "737876441172"
REGION = "us-east-1"


def check_identity(session):
    if session.region_name != REGION:
        raise ValueError("Deployment Region must be us-east-1 for the team's existing Lambdas.")
    client = session.client("sts", config=Config(connect_timeout=5, read_timeout=10,
                                                retries={"total_max_attempts": 1}))
    identity = client.get_caller_identity()
    if identity.get("Account") != ACCOUNT:
        raise ValueError("AWS account differs from the team's configured account; deployment must stop.")
    return {"account": identity["Account"], "region": session.region_name,
            "identity_verified": True, "deployment_permissions_verified": False,
            "resources_created": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)
    try:
        session = boto3.Session(profile_name=args.profile, region_name=REGION)
        if session.get_credentials() is None:
            print("AWS deployment credentials are missing. Configure a Workshop Studio profile; a Bedrock key alone cannot deploy.", file=sys.stderr)
            return 1
        report = check_identity(session)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        messages = {
            "ExpiredToken": "AWS credentials have expired. Copy fresh temporary credentials from Workshop Studio.",
            "ExpiredTokenException": "AWS credentials have expired. Copy fresh temporary credentials from Workshop Studio.",
            "InvalidClientTokenId": "AWS rejected the credential identity. Copy all three fields from the same Workshop Studio session.",
            "SignatureDoesNotMatch": "AWS rejected the credential signature. Recopy the access key, secret and session token together without quotes.",
            "AccessDenied": "AWS refused the identity request. Check access with your workshop administrator.",
            "AccessDeniedException": "AWS refused the identity request. Check access with your workshop administrator.",
        }
        print(messages.get(code, "AWS rejected the identity request. Check the workshop session and configured profile."), file=sys.stderr)
        return 1
    except BotoCoreError:
        print("AWS identity check failed. Check the profile, temporary session expiry, connectivity and STS access.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
