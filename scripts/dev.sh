#!/usr/bin/env bash
# Run a command inside the dev container, from the repository root:
#   scripts/dev.sh npm ci
#   scripts/dev.sh npm run dev        # http://localhost:4321/
#   DEV_LAN=1 scripts/dev.sh npm run dev   # also reachable from a phone on the same Wi-Fi
# Only the repository and a node_modules volume are mounted. Nothing from $HOME is.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
[ "$#" -gt 0 ] || { echo "usage: scripts/dev.sh <command> [args...]" >&2; exit 2; }

# The image tag is the Dockerfile's hash, so editing the Dockerfile rebuilds it.
image="spellcaster-site-dev:$(shasum -a 256 .devcontainer/Dockerfile | cut -c1-12)"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  docker build --tag "$image" .devcontainer
fi

# One node_modules volume per checkout, so clones and worktrees don't share installs.
volume="spellcaster-site-node-modules-$(printf '%s' "$root" | shasum -a 256 | cut -c1-12)"
args=(--rm --init --cap-drop=ALL --security-opt=no-new-privileges --shm-size=1g
  --volume "$root:/work" --volume "$volume:/work/node_modules")
[ -t 0 ] && [ -t 1 ] && args+=(--interactive --tty)

# Publish the port only for the servers, so tests can run while `npm run dev` is up.
case " $* " in
  *" run dev "* | *" run preview "*)
    if [ "${DEV_LAN:-}" = 1 ]; then
      args+=(--publish "0.0.0.0:4321:4321")
      echo "DEV_LAN=1: also serving on http://$(ipconfig getifaddr en0 2> /dev/null || hostname):4321/" >&2
    else
      args+=(--publish "127.0.0.1:4321:4321")
    fi
    ;;
esac

exec docker run "${args[@]}" "$image" "$@"
