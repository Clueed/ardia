# Clueed/ardia

A personal fork of [mantrakp04/ardia](https://github.com/mantrakp04/ardia), built for my own use.

## Branches

- `main` mirrors upstream exactly. Never commit to it.
- `mine` is `main` plus the fork-only commits (bundle ID, no updater, these scripts). Keep them few and small: new
  files over edits to upstream ones. It is rebased, and never merged into another branch.
- Feature branches hold the fork's features. Each is cut from `main` (or stacked on another feature) and never
  contains `mine`, so it can still become a PR against `mantrakp04/ardia`. They take upstream's changes by merging
  their base and are never rebased. `scripts/fork/features` lists them as `<branch> <base>`, bases first.
- `fork` is what gets built: `mine` plus a merge of every feature branch. `update.sh` rebuilds it each time, so
  never commit to it; a fix goes on the feature branch or on `mine`.

## For agents

These override `AGENTS.md` in this fork:

- Never commit to `main` or `fork`, despite "commit straight to `main`". Fork-only changes are commits on `mine`;
  feature work goes on its feature branch.
- Never force-push `mine` without asking, and never rebase a feature branch.
- To take upstream's changes, run `scripts/fork/update.sh`, not the steps by hand.
- A new feature: cut its branch from `main`, push it, and add a line for it to `scripts/fork/features` on `mine`.

## Set up a clone

```sh
git clone https://github.com/Clueed/ardia.git && cd ardia
git fetch origin fork && git checkout -b fork --track origin/fork
scripts/fork/setup.sh
```

`setup.sh` adds `upstream` with pushing to it turned off, turns on rerere and the rebase settings, adds a
`git sync` alias, and creates `mine` and `fork` tracking origin's. It is safe to run again.

## Take upstream's changes

```sh
scripts/fork/update.sh            # sync main, rebase mine, merge into features, rebuild fork, build
scripts/fork/update.sh --push     # the same, then push the features and force-push mine and fork with lease
```

Run it from `fork` with nothing uncommitted. It fast-forwards `main` from upstream and pushes it to the fork,
replays `mine` onto it and prints a `range-diff` of what that did, merges each feature's base into it, and rebuilds
`fork` as `mine` plus every feature. It never checks anything out: other branches move by ref, the checked-out one
with `git reset --keep`. It builds only when `fork` is checked out; `--no-build` skips that.

On a conflict it stops and names the merge to do by hand: check out that branch, merge its base (or rebase `mine`
onto `main`), resolve, commit, and run it again. A feature's resolution stays in its history, so it is done once;
`fork` only conflicts where `mine` and a feature change the same lines.

## Build

```sh
scripts/fork/build.sh
```

It leaves `dist/fork/Ardia Fork.app` (and a zip) signed ad hoc. It downloads upstream's prebuilt engine, so it
takes minutes, not the hours a Chromium build does. Changing anything under `engine/` would mean building
Chromium (`docs/engine-build.md`); keep fork changes out of it.

On another Mac: quit Ardia, move the official `Ardia.app` to the Trash, and unzip the fork into `/Applications`.
The first launch needs a right-click › Open, or `xattr -dr com.apple.quarantine "/Applications/Ardia Fork.app"`,
and asks for the "Ardia Safe Storage" keychain item: choose Always Allow.

## What makes it the fork

`apps/browser/macos/Fork.xcconfig` keeps it to three things:

- **The official bundle ID `com.ardia.browser`**, so the fork takes over the official app's place: the same profile
  (`~/Library/Application Support/com.ardia.browser`), settings, preferences and keychain key, with nothing to copy.
  It replaces Ardia rather than sitting beside it: never keep both installed or run both at once.
- **No updater.** `Info.plist` takes its feed and key from `ARDIA_UPDATE_FEED_URL` and `ARDIA_UPDATE_PUBLIC_KEY`,
  which the fork leaves unset, so it never checks for updates and an official release can't replace it.
- **Ad hoc signing** (`AdHoc.xcconfig`): no Apple team needed. Passkeys and the shared keychain groups don't work.

Telemetry is opt-in and off unless you tick it during onboarding; leave it unticked.

## Update

Take upstream's changes from `fork` (that builds it too), quit the app and copy the new `Ardia Fork.app` over the old
one. The profile lives outside the app, so nothing is lost.

## Known gaps

- The fork builds upstream's `main`, which can be ahead of the latest official release, and may move the profile to
  a newer format. Going back to an older official Ardia on that profile afterwards isn't safe; back up
  `~/Library/Application Support/com.ardia.browser` first if you might.
