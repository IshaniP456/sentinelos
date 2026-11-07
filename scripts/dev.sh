#!/usr/bin/env bash
# Author: Tishneet. Compose entry point; run from the repository root.
set -euo pipefail
exec bash scripts/docker.sh compose "$@"
