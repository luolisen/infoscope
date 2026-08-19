#!/usr/bin/env bash
set -euo pipefail

base_ref=${1:?base ref is required}
head_ref=${2:?head ref is required}
pr_title=${3:-}
labels=",${4:-},"

fail() {
  printf 'release freeze gate: %s\n' "$1" >&2
  exit 1
}

case "$pr_title" in
  fix:*|docs:*|test:*|chore\(release\):*|chore\(security\):*) ;;
  *) fail "PR title must use an allowed release-freeze prefix" ;;
esac

if git log --format='%s' "$base_ref..$head_ref" | grep -Eiq '^feat([(:]|$)'; then
  fail "feat commits are prohibited during the release freeze"
fi

[[ "$labels" == *,release-approved,* ]] \
  || fail "Alan must apply the release-approved label"

changed_files=$(git diff --name-only "$base_ref...$head_ref")

if grep -Eq '^(backend/alembic/|contracts/)' <<<"$changed_files"; then
  fail "database migrations and frozen contracts cannot change during the release freeze"
fi

if grep -Eq '^(backend/src/|frontend/src/)' <<<"$changed_files"; then
  if [[ "$labels" != *,release-critical-fix,* && "$labels" != *,release-security,* ]]; then
    fail "runtime changes require release-critical-fix or release-security"
  fi
fi

if grep -Eq '(^|/)(package-lock\.json|pnpm-lock\.yaml|uv\.lock)$' <<<"$changed_files"; then
  [[ "$labels" == *,release-security,* ]] \
    || fail "dependency lock changes require release-security"
fi

printf 'release freeze gate: policy passed\n'
