#!/usr/bin/env bash
# Takes upstream's changes into the fork without checking anything out:
#   1. fast-forwards `main` to upstream and pushes it to origin,
#   2. replays `mine` onto it and shows a range-diff of what that did,
#   3. merges each feature branch's base into it (scripts/fork/features, `<branch> <base>` per line),
#   4. rebuilds `fork` as `mine` plus a merge of every feature branch,
#   5. builds when `fork` is checked out.
#
#   scripts/fork/update.sh [--no-build] [--push]
#   scripts/fork/update.sh -h | --help
#
# --no-build  skips scripts/fork/build.sh.
# --push      pushes the feature branches, then force-pushes `mine` and `fork` with lease.
#
# The checked-out branch moves with `git reset --keep`, the others with update-ref, so run it with nothing
# uncommitted. On a conflict it stops and names the merge to do by hand; do it, commit, and run it again.
# Feature-branch merges stay in their history, so `fork` itself only conflicts where `mine` and a feature
# touch the same lines.
set -euo pipefail

main() {
  local build=1 push=0 arg
  for arg in "$@"; do
    case "$arg" in
      -h | --help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
      --no-build) build=0 ;;
      --push) push=1 ;;
      *) echo "error: unknown option $arg" >&2; exit 2 ;;
    esac
  done

  root=$(git rev-parse --show-toplevel)
  cd "$root"

  if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ] ||
    git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    echo "error: a rebase or merge is in progress; finish or abort it first" >&2
    exit 1
  fi
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "error: commit or set aside the uncommitted changes first" >&2
    exit 1
  fi
  if [ "$(git branch --show-current)" = main ]; then
    echo "error: main is checked out; check out fork or mine" >&2
    exit 1
  fi

  git fetch --quiet origin
  git fetch --quiet upstream

  echo "==> main"
  local old_main
  old_main=$(git rev-parse main)
  git fetch --quiet upstream main:main
  git push --quiet origin main:refs/heads/main
  echo "main: $(git rev-list --count "$old_main..main") new upstream commits"

  echo "==> mine"
  local old_mine new_mine
  old_mine=$(git rev-parse mine)
  if git merge-base --is-ancestor main mine; then
    echo "mine: already on main"
  else
    new_mine=$(git replay --ref-action=print --onto main "$(git merge-base main mine)..mine" | awk '{ print $3 }') || {
      echo "error: mine doesn't replay cleanly onto main; check out mine, git rebase main, then run this again" >&2
      exit 1
    }
    move mine "$new_mine" "$old_mine"
    git --no-pager range-diff "$old_main..$old_mine" main..mine || true
  fi

  echo "==> Features"
  local features=() branch base
  while read -r branch base; do
    [ -n "$branch" ] || continue
    features+=("$branch")
    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
      git branch --quiet --track "$branch" "origin/$branch"
    elif git show-ref --verify --quiet "refs/remotes/origin/$branch" &&
      [ "$(git rev-parse "$branch")" != "$(git rev-parse "origin/$branch")" ] &&
      git merge-base --is-ancestor "$branch" "origin/$branch"; then
      move "$branch" "$(git rev-parse "origin/$branch")" "$(git rev-parse "$branch")"
    fi
    if git merge-base --is-ancestor "$base" "$branch"; then
      echo "$branch: has $base"
    else
      merge_into "$branch" "$base"
      echo "$branch: merged $base"
    fi
  done < <(git show mine:scripts/fork/features)

  echo "==> fork"
  if fork_is_current "${features[@]}"; then
    echo "fork: up to date"
  else
    local old_fork head
    old_fork=$(git rev-parse -q --verify refs/heads/fork || true)
    head=$(git rev-parse mine)
    for branch in "${features[@]}"; do
      git merge-base --is-ancestor "$branch" "$head" && continue
      head=$(merge_commit "$head" "$branch" "Fork: merge $branch") || {
        echo "error: $branch conflicts with mine or an earlier feature; fix it on $branch or mine, then run this again" >&2
        exit 1
      }
    done
    move fork "$head" "$old_fork"
    echo "fork: mine + ${features[*]}"
  fi

  if [ "$build" = 1 ]; then
    if [ "$(git branch --show-current)" = fork ]; then
      echo "==> Build"
      "$root/scripts/fork/build.sh"
    else
      echo "build skipped: check out fork to build it"
    fi
  fi

  if [ "$push" = 1 ]; then
    git push --quiet origin "${features[@]}"
    git push --quiet --force-with-lease=mine:"$(git rev-parse -q --verify origin/mine || true)" origin mine
    git push --quiet --force-with-lease=fork:"$(git rev-parse -q --verify origin/fork || true)" origin fork
    echo "pushed: ${features[*]} mine fork"
  else
    echo "not pushed: run again with --push"
  fi
}

move() {
  local branch=$1 new=$2 old=$3
  if [ "$(git branch --show-current)" = "$branch" ]; then
    git reset --quiet --keep "$new"
  else
    git update-ref -m "fork/update.sh" "refs/heads/$branch" "$new" ${old:+"$old"}
  fi
}

merge_commit() {
  local ours=$1 theirs=$2 message=$3 tree
  tree=$(git merge-tree --write-tree --no-messages "$ours" "$theirs" | head -1) || return 1
  git commit-tree "$tree" -p "$ours" -p "$theirs" -m "$message"
}

merge_into() {
  local branch=$1 base=$2 old new
  old=$(git rev-parse "$branch")
  new=$(merge_commit "$old" "$base" "Merge $base into $branch") || {
    echo "error: $base conflicts with $branch in:" >&2
    git merge-tree --write-tree --name-only --no-messages "$old" "$base" | tail -n +2 | sed 's/^/  /' >&2 || true
    echo "check out $branch, git merge $base, commit, then run this again" >&2
    exit 1
  }
  move "$branch" "$new" "$old"
}

fork_is_current() {
  git show-ref --verify --quiet refs/heads/fork || return 1
  local ref
  for ref in mine "$@"; do
    git merge-base --is-ancestor "$ref" fork || return 1
  done
  [ -z "$(git rev-list --no-merges fork --not mine "$@")" ]
}

main "$@"
exit
