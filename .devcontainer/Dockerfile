# The only place npm runs on a developer machine (scripts/dev.sh). The container sees the
# repository and a node_modules volume, never ~/.aws, gh, SSH keys or 1Password, so a
# malicious dependency can't reach cloud or GitHub sessions.
# Node matches .node-version (a unit test checks). Dependabot bumps the digest.
FROM node:25-bookworm-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370

# Must equal @playwright/test in package.json (a unit test checks).
ARG PLAYWRIGHT_VERSION=1.63.0
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Chromium and WebKit plus their system libraries, for the E2E projects.
RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium webkit \
  && rm -rf /root/.npm /var/lib/apt/lists/*

# The node_modules volume inherits this owner the first time it's mounted.
RUN mkdir -p /work/node_modules && chown -R node:node /work
USER node
WORKDIR /work
