#!/usr/bin/env bash
# Sets up a clone of the fork the way FORK.md describes. Safe to run again.
#
#   scripts/fork/setup.sh
#   scripts/fork/setup.sh -h | --help
#
# Adds the upstream remote with pushing to it turned off, turns on rerere and the rebase settings,
# adds the `git sync` alias, and creates a local `mine` that tracks origin/mine. It moves the checkout
# to `mine` only when it is on `main` with nothing uncommitted.
set -euo pipefail

case "${1:-}" in
  -h | --help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
esac

cd "$(dirname "$0")/../.."

if git remote get-url upstream >/dev/null 2>&1; then
  git remote set-url upstream https://github.com/mantrakp04/ardia.git
else
  git remote add upstream https://github.com/mantrakp04/ardia.git
fi
git remote set-url --push upstream DISABLE
git config remote.pushDefault origin
git config rerere.enabled true
git config rerere.autoUpdate true
git config rebase.updateRefs true
git config pull.rebase true
git config alias.sync '!git fetch upstream && git fetch upstream main:main && git push origin upstream/main:refs/heads/main'

git fetch --quiet origin
git fetch --quiet upstream

if ! git show-ref --verify --quiet refs/heads/mine; then
  git branch --quiet --track mine origin/mine
fi
git branch --quiet --set-upstream-to=origin/mine mine

if [ "$(git branch --show-current)" = main ] && [ -z "$(git status --porcelain)" ]; then
  git switch --quiet mine
fi

echo "fork: set up, on $(git branch --show-current)"
