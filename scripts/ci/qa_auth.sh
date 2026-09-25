# Source this (don't run it) in each QA step that needs the password, with the QA role's
# credentials in place:
#
#   . scripts/ci/qa_auth.sh
#
# It reads the password from SSM and sets, for this step only:
#   QA_AUTH_HEADER           the whole Authorization header: "Basic " and base64 of qa:<password>
#   TF_VAR_basic_auth_sha256 its SHA-256 in hex, which is all the CloudFront function holds
# Every one of them is masked first. Nothing goes to GITHUB_ENV or to a file, so the next step,
# and anything it runs, never sees them.

qa_auth_password=$(aws ssm get-parameter --name /portfolio/qa/basic-auth-password --with-decryption \
  --query Parameter.Value --output text) || return 1
if [ "${#qa_auth_password}" -lt 24 ]; then
  echo "::error::The QA password in SSM is shorter than 24 characters. Production can read the function's digest, so make it long and random (docs/qa.md)."
  return 1
fi
echo "::add-mask::${qa_auth_password}"
qa_auth_base64=$(printf 'qa:%s' "$qa_auth_password" | base64 -w0)
echo "::add-mask::${qa_auth_base64}"
QA_AUTH_HEADER="Basic ${qa_auth_base64}"
TF_VAR_basic_auth_sha256=$(printf '%s' "$QA_AUTH_HEADER" | sha256sum | cut -d' ' -f1)
echo "::add-mask::${TF_VAR_basic_auth_sha256}"
export QA_AUTH_HEADER TF_VAR_basic_auth_sha256
unset qa_auth_password qa_auth_base64
