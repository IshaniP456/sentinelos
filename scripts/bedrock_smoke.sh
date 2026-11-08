#!/usr/bin/env bash
# Author: Tishneet. Never put credential values on the command line or in Git.
set -euo pipefail
bash scripts/docker.sh build --platform linux/arm64 -f backend/Dockerfile -t sentinelos-bedrock-smoke .
run_args=(run --platform linux/arm64 --rm -v "$PWD:/app:ro")
if [[ -f .env.local ]]; then
  run_args+=(--env-file .env.local)
fi
if [[ -d "$HOME/.aws" ]]; then
  run_args+=(-v "$HOME/.aws:/root/.aws:ro")
fi
for config_name in AWS_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_BEARER_TOKEN_BEDROCK BEDROCK_MODEL_ID AWS_DEFAULT_REGION BEDROCK_FORCE_TOOL; do
  if [[ -n "${!config_name:-}" ]]; then
    run_args+=(-e "$config_name")
  fi
done
bash scripts/docker.sh "${run_args[@]}" sentinelos-bedrock-smoke python -m scripts.bedrock_smoke
