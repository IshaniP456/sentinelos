#!/usr/bin/env bash
# Author: Tishneet. Run inside the isolated SAM tools image with repo at /app.
set -euo pipefail
sam validate --lint --template-file backend/workflows/template.yaml
sam build --template-file backend/workflows/template.yaml --build-dir /tmp/sentinel-sam --no-cached --build-in-source
python3 scripts/check_lambda_artifact.py /tmp/sentinel-sam/WorkflowFunction
