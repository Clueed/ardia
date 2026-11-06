# Clueed/ardia

A personal fork of [mantrakp04/ardia](https://github.com/mantrakp04/ardia), built for my own use.

## Branches

- `main` mirrors upstream exactly. Never commit to it.
- `mine` is `main` plus the fork's commits. Keep them few and small: new files over edits to upstream ones.
- Work meant for upstream goes on its own branch cut from `main`, pushed to `origin`, and opened as a PR against
  `mantrakp04/ardia`.

## For agents

These override `AGENTS.md` in this fork:

- Never commit to `main`, despite "commit straight to `main`". Fork changes are commits on `mine`.
- Never force-push `mine` without asking.
- To take upstream's changes, run `scripts/fork/update.sh`, not the steps by hand.

## Set up a clone

```sh
git clone https://github.com/Clueed/ardia.git && cd ardia
git fetch origin mine && git checkout -b mine --track origin/mine
scripts/fork/setup.sh
```

`setup.sh` adds `upstream` with pushing to it turned off, turns on rerere and the rebase settings, and adds a
`git sync` alias. It is safe to run again.

## Take upstream's changes

```sh
scripts/fork/update.sh            # sync main, rebase mine, range-diff, build
scripts/fork/update.sh --push     # the same, then force-push mine with lease
```

It fast-forwards `main` from upstream and pushes it to the fork, rebases `mine` onto it, and prints a `range-diff`
of what the rebase did to the fork's commits. On a conflict it stops mid-rebase: resolve, `git rebase --continue`,
run it again. rerere replays resolutions it has seen before. `--no-build` skips the build.

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

Take upstream's changes, run `scripts/fork/build.sh`, quit the app and copy the new `Ardia Fork.app` over the old
one. The profile lives outside the app, so nothing is lost.

## Known gaps

- The fork builds upstream's `main`, which can be ahead of the latest official release, and may move the profile to
  a newer format. Going back to an older official Ardia on that profile afterwards isn't safe; back up
  `~/Library/Application Support/com.ardia.browser` first if you might.
