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

# Astro records a running dev or preview server in .astro/*.json by PID. Each container has
# its own PIDs and network, so a lock left by another (or a killed) container means nothing
# here, and a reused PID would make Astro refuse to start.
rm -f .astro/dev.json .astro/preview.json

# One node_modules volume per checkout, so clones and worktrees don't share installs.
volume="spellcaster-site-node-modules-$(printf '%s' "$root" | shasum -a 256 | cut -c1-12)"
args=(--rm --init --cap-drop=ALL --security-opt=no-new-privileges --shm-size=1g)

# The repository is read-only in the container, apart from what the tools write. So a
# malicious package can't change what acts on the host (git's config and hooks, this script,
# the CI helpers and their tests, CLAUDE.md, Claude Code's settings, the ruleset, docs) or
# add a file at the root, like .mcp.json. The exceptions:
# - npm install, uninstall and update need the root writable, since npm replaces
#   package.json and the lockfile by renaming. Only npm itself runs then (.npmrc:
#   ignore-scripts), not package code.
# - tests/ci stays read-only inside the writable tests/, because it also runs on the host.
writable=(src public tests dist .astro test-results playwright-report package.json astro.config.ts
  eslint.config.ts playwright.config.ts vitest.config.ts tsconfig.json scripts/og-images.ts)
mkdir -p node_modules dist .astro test-results playwright-report
case "${1:-} ${2:-}" in
  "npm install" | "npm i" | "npm uninstall" | "npm update")
    args+=(--volume "$root:/work")
    ;;
  *)
    args+=(--volume "$root:/work:ro")
    for path in "${writable[@]}"; do args+=(--volume "$root/$path:/work/$path"); done
    args+=(--volume "$root/tests/ci:/work/tests/ci:ro")
    ;;
esac
args+=(--volume "$volume:/work/node_modules")
# Private files never enter the container: from M4, infra/ holds Terraform state and the
# settings that name the AWS account.
for path in infra .notes; do
  if [ -e "$path" ]; then args+=(--mount "type=tmpfs,destination=/work/$path"); fi
done
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

# Ctrl-C stops the container, not this script, so the check below still runs.
trap : INT
status=0
docker run "${args[@]}" "$image" "$@" || status=$?

# The writable folders could still receive a file that acts on the host: Claude Code reads
# any CLAUDE.md, CLAUDE.local.md, .mcp.json or .claude/ it finds, and git runs a nested
# repository's core.fsmonitor when used inside it. Stop loudly if one appeared.
planted=$(find . -path ./node_modules -prune -o -path ./.git -prune -o \
  \( -name .git -o -name CLAUDE.md -o -name CLAUDE.local.md -o -name .mcp.json -o -name .claude \) \
  ! -path ./CLAUDE.md ! -path ./.claude -print)
if [ -n "$planted" ]; then
  echo "dev.sh: STOP. The container made files that would act on your Mac:" >&2
  echo "$planted" >&2
  echo "Don't run git or Claude Code in those folders. Look at the files, then delete them." >&2
  exit 97
fi
exit "$status"
