#!/usr/bin/env bash
# Takes upstream's changes into the fork: fast-forwards `main` to upstream and pushes it to origin,
# rebases `mine` onto it, shows what the rebase did, and builds. Run it from `mine` with nothing uncommitted.
#
#   scripts/fork/update.sh [--no-build] [--push]
#   scripts/fork/update.sh -h | --help
#
# --no-build  skips scripts/fork/build.sh.
# --push      force-pushes `mine` to origin (with lease) once the rebase and the build succeed.
#
# On a rebase conflict it stops with the rebase in progress: fix the files, `git add` them,
# `git rebase --continue`, then run it again. rerere remembers the fix for next time.
set -euo pipefail

build=1
push=0
for arg in "$@"; do
  case "$arg" in
    -h | --help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    --no-build) build=0 ;;
    --push) push=1 ;;
    *) echo "error: unknown option $arg" >&2; exit 2 ;;
  esac
done

root=$(cd "$(dirname "$0")/../.." && pwd -P)
cd "$root"

if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
  echo "error: a rebase is in progress; finish it with git rebase --continue or --abort" >&2
  exit 1
fi
if [ "$(git branch --show-current)" != mine ]; then
  echo "error: run this from mine, not $(git branch --show-current)" >&2
  exit 1
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "error: commit or set aside the uncommitted changes first" >&2
  exit 1
fi

git fetch --quiet origin
git fetch --quiet upstream
old_main=$(git rev-parse main)
old_mine=$(git rev-parse mine)

echo "==> main"
git fetch --quiet upstream main:main
git push --quiet origin main:refs/heads/main
echo "main: $(git rev-list --count "$old_main..main") new upstream commits"

echo "==> mine"
if ! git merge-base --is-ancestor main mine; then
  git rebase main || {
    echo "error: the rebase stopped on a conflict; resolve it, git rebase --continue, then run this again" >&2
    exit 1
  }
fi
git --no-pager range-diff "$old_main..$old_mine" main..mine || true

if [ "$build" = 1 ]; then
  echo "==> Build"
  "$root/scripts/fork/build.sh"
fi

if [ "$push" = 1 ]; then
  git push --force-with-lease=mine:"$(git rev-parse origin/mine)" origin mine
else
  echo "not pushed: git push --force-with-lease origin mine"
fi
