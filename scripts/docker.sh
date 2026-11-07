#!/usr/bin/env bash
# Author: Tishneet. Discover Docker and its credential helper without shell edits.
set -euo pipefail
if ! command -v docker >/dev/null 2>&1; then
  if [[ -x "$HOME/.docker/bin/docker" ]]; then
    export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
  else
    echo 'Install/start Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/' >&2
    exit 1
  fi
elif [[ -d /Applications/Docker.app/Contents/Resources/bin ]]; then
  export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
fi
exec docker "$@"
