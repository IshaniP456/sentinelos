#!/usr/bin/env bash
# Post-judging teardown for the SentinelOS demo API.
#
# WHY: the live demo runs a demo-grade API Gateway authorizer that grants admin
# to ANY caller (see backend/api/demo_authorizer.py). That is fine while we are
# demoing, but we must NOT leave a public "everyone is admin" endpoint running
# after judging. Run this once judging is over.
#
# This script does NOTHING unless you pass an explicit mode, so it can't fire by
# accident:
#   ./scripts/post_judging_teardown.sh denyall       # lock the API (reversible)
#   ./scripts/post_judging_teardown.sh restore        # undo denyall (re-grant, for Cognito work later)
#   ./scripts/post_judging_teardown.sh delete-stack    # remove the API entirely (nuclear)
#
# Requires valid AWS credentials for account 737876441172 / us-east-1.
set -euo pipefail

FN="sentinelos-api-AuthorizerFunction-zDNAXNlw4mf4"   # the demo authorizer Lambda
STACK="sentinelos-api"
REGION="us-east-1"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

build_pkg() {   # $1 = "Deny" or "Allow"  -> prints zip path
  local effect="$1"
  mkdir -p "$TMP/pkg/backend/api"
  : > "$TMP/pkg/backend/__init__.py"
  : > "$TMP/pkg/backend/api/__init__.py"
  # The Authorizer Lambda's configured handler is backend.api.demo_authorizer.authorize
  # and it imports nothing else, so this minimal package is a complete replacement.
  cat > "$TMP/pkg/backend/api/demo_authorizer.py" <<PY
def authorize(event, context=None):
    return {
        "principalId": "locked",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": "${effect}", "Resource": "*"}
            ],
        },
    }
PY
  ( cd "$TMP/pkg" && zip -qr "$TMP/auth.zip" . )
  echo "$TMP/auth.zip"
}

case "${1:-}" in
  denyall)
    echo ">> Flipping the demo authorizer to DENY-ALL (locks every route)..."
    ZIP="$(build_pkg Deny)"
    aws lambda update-function-code --region "$REGION" --function-name "$FN" \
      --zip-file "fileb://$ZIP" --query 'LastUpdateStatus' --output text
    echo ">> Done. The public API now denies all callers. The hosted UI will stop working (expected)."
    ;;
  restore)
    echo ">> Restoring the demo authorizer to ALLOW (re-grants admin to all — only for later dev)..."
    ZIP="$(build_pkg Allow)"
    aws lambda update-function-code --region "$REGION" --function-name "$FN" \
      --zip-file "fileb://$ZIP" --query 'LastUpdateStatus' --output text
    echo ">> NOTE: this re-opens the demo authorizer. Do not leave it public."
    ;;
  delete-stack)
    echo ">> DELETING the entire $STACK stack (API Gateway + Lambdas + authorizer). This is irreversible."
    read -r -p "Type the stack name to confirm: " c
    [ "$c" = "$STACK" ] || { echo "Mismatch; aborting."; exit 1; }
    aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
    echo ">> delete-stack requested. Track with: aws cloudformation describe-stacks --stack-name $STACK"
    ;;
  *)
    echo "Usage: $0 {denyall|restore|delete-stack}"
    echo "  denyall       lock the API (reversible via 'restore') — RECOMMENDED post-judging"
    echo "  restore       re-open the demo authorizer (dev only)"
    echo "  delete-stack  remove the API entirely (nuclear)"
    exit 2
    ;;
esac
