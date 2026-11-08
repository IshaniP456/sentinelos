"""DEMO-GRADE API Gateway authorizer — grants administrator to every caller.

This exists only so the hackathon demo can exercise the Approve / Revoke / Reset
admin routes through the deployed API, which runs AUTH_MODE=prod (the workflow
factory refuses open/dev in AWS) and therefore needs an authorizer's claims.

⚠️ This is NOT real authentication. It authorizes everyone as "demo-admin" so
the walkthrough works. A production deployment would replace this with a Cognito
user-pool / real identity provider. Labeled as such on the status slide.

REQUEST-type, no identity source → invoked on every request (incl. OPTIONS so
CORS preflight still passes). Returns Allow + admin claims that require_admin
reads from requestContext.authorizer.
"""


def authorize(event, context=None):
    method_arn = event.get("methodArn") or event.get("routeArn") or "*"
    # Allow the whole API stage so every route is permitted.
    if "/" in method_arn and method_arn.startswith("arn:"):
        parts = method_arn.split("/")
        resource = f"{parts[0]}/{parts[1] if len(parts) > 1 else '*'}/*"
    else:
        resource = "*"
    return {
        "principalId": "demo-admin",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": "Allow", "Resource": resource}
            ],
        },
        # require_admin (prod) reads these from requestContext.authorizer.
        # Use colon-free keys ("role", "groups") — API Gateway mangles context
        # keys containing a colon (so "cognito:groups" would be dropped).
        "context": {"email": "demo-admin@scu.edu", "role": "admin", "groups": "admin"},
    }
