#!/usr/bin/env bash
set -euo pipefail

build_reviewers_json() {
  if [[ -z "${CD_APPROVER_GITHUB_USERNAMES:-}" ]]; then
    echo '[]'
    return
  fi

  reviewers='[]'
  IFS=',' read -ra usernames <<<"${CD_APPROVER_GITHUB_USERNAMES}"
  for raw_username in "${usernames[@]}"; do
    username="$(echo "${raw_username}" | xargs)"
    if [[ -z "${username}" ]]; then
      continue
    fi

    user_id="$(gh api "users/${username}" --jq .id)"
    reviewers="$(jq -c \
      --argjson user_id "${user_id}" \
      '. + [{type: "User", id: $user_id}]' <<<"${reviewers}")"
    echo "Configured reviewer: ${username} (${user_id})" >&2
  done

  echo "${reviewers}"
}

CONFIG_PATH="${1:-.github/environments/cd-approval.json}"
ENVIRONMENT_NAME="$(jq -r '.name' "${CONFIG_PATH}")"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
REVIEWERS_JSON="$(build_reviewers_json)"

payload="$(jq -c \
  --argjson reviewers "${REVIEWERS_JSON}" \
  '{
    wait_timer: .wait_timer,
    prevent_self_review: .prevent_self_review,
    deployment_branch_policy: .deployment_branch_policy,
    reviewers: $reviewers
  }' "${CONFIG_PATH}")"

echo "Ensuring GitHub Environment '${ENVIRONMENT_NAME}' on ${REPO}"
gh api \
  --method PUT \
  "repos/${REPO}/environments/${ENVIRONMENT_NAME}" \
  --input - <<<"${payload}"

if [[ "${REVIEWERS_JSON}" == "[]" ]]; then
  echo "Warning: no reviewers configured. Set repository variable CD_APPROVER_GITHUB_USERNAMES to enforce manual approval." >&2
fi

echo "Environment '${ENVIRONMENT_NAME}' is ready."
