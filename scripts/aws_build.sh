#!/usr/bin/env bash
# Author: Tishneet. Match Lambda's platform even when the host differs.
set -euo pipefail
bash scripts/docker.sh build --platform linux/arm64 -f backend/Dockerfile.sam -t sentinelos-sam-tools .
bash scripts/docker.sh run --platform linux/arm64 --rm -v "$PWD:/app:ro" sentinelos-sam-tools bash scripts/check_sam.sh
