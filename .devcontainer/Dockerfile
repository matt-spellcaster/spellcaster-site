# The only place npm runs on a developer machine (scripts/dev.sh). The container sees the
# repository and a node_modules volume, never ~/.aws, gh, SSH keys or 1Password, so a
# malicious dependency can't reach cloud or GitHub sessions.
# The tag's Node version equals .node-version, which CI uses (a unit test checks). Dependabot
# bumps the tag and digest; bump .node-version in the same pull request.
FROM node:24.21.0-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6

# Must equal @playwright/test in package.json (a unit test checks).
ARG PLAYWRIGHT_VERSION=1.63.0
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# No usage data leaves the container, and no daily "is there a newer Astro?" call: versions are
# pinned and Dependabot proposes updates. That check also writes .astro/settings.json, which
# (with Docker Desktop's file sharing) restarted the dev server.
ENV ASTRO_TELEMETRY_DISABLED=1 ASTRO_DISABLE_UPDATE_CHECK=true

# Chromium and WebKit plus their system libraries, for the E2E projects.
RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium webkit \
  && rm -rf /root/.npm /var/lib/apt/lists/*

# The node_modules volume inherits this owner the first time it's mounted.
RUN mkdir -p /work/node_modules && chown -R node:node /work
USER node
WORKDIR /work
