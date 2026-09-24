#!/usr/bin/env bash
# Install the pinned Terraform and TFLint (linux_amd64) into $RUNNER_TEMP/bin, checking each
# download against a pinned SHA-256. Versions and checksums come from the workflow's env
# block. Usage: scripts/ci/install_terraform.sh
set -euo pipefail
bin="${RUNNER_TEMP:?}/bin"
mkdir -p "$bin"
cd "$RUNNER_TEMP"

zip="terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
curl -sSfL -o "$zip" "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${zip}"
echo "${TERRAFORM_SHA256}  ${zip}" | sha256sum --check --strict
unzip -oq "$zip" terraform -d "$bin"

curl -sSfL -o tflint.zip \
  "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip"
echo "${TFLINT_SHA256}  tflint.zip" | sha256sum --check --strict
unzip -oq tflint.zip tflint -d "$bin"

echo "$bin" >> "$GITHUB_PATH"
