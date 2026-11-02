# Clueed/ardia

A personal fork of [mantrakp04/ardia](https://github.com/mantrakp04/ardia), built for my own use.

## Branches

- `main` mirrors upstream exactly. Never commit to it.
- `mine` is `main` plus the fork's commits. Keep them few and small: new files over edits to upstream ones.

## Set up a clone

```sh
git clone https://github.com/Clueed/ardia.git && cd ardia
git remote add upstream https://github.com/mantrakp04/ardia.git
git remote set-url --push upstream DISABLE
git config remote.pushDefault origin
git config rerere.enabled true
git config rebase.updateRefs true
git config pull.rebase true
git config alias.sync '!git fetch upstream && git fetch upstream main:main && git push origin upstream/main:refs/heads/main'
git switch mine
```

## Take upstream's changes

```sh
git sync
git rebase main
git range-diff main@{1} mine@{1} main mine
git push --force-with-lease origin mine
```

`git sync` fast-forwards `main` from upstream and pushes it to the fork; run it from `mine`, not `main`.
rerere replays conflict resolutions it has seen before. `range-diff` shows what the rebase did to the fork's commits.

## Build

```sh
scripts/fork/build.sh
```

It leaves `dist/fork/Ardia Fork.app` (and a zip) signed ad hoc. It downloads upstream's prebuilt engine, so it
takes minutes, not the hours a Chromium build does. Changing anything under `engine/` would mean building
Chromium (`docs/engine-build.md`); keep fork changes out of it.

On another Mac, unzip it into `/Applications`. The first launch needs a right-click › Open, or
`xattr -dr com.apple.quarantine "/Applications/Ardia Fork.app"`.

## What makes it the fork

All in `apps/browser/macos/Fork.xcconfig`:

- **Bundle ID `com.clueed.ardia`**, so its profile, settings and caches
  (`~/Library/Application Support/com.clueed.ardia`) stay apart from an official Ardia on the same Mac.
- **No updater.** `Info.plist` takes its feed and key from `ARDIA_UPDATE_FEED_URL` and `ARDIA_UPDATE_PUBLIC_KEY`,
  which the fork leaves unset, so it never checks for updates and an official release can't replace it.
- **Ad hoc signing** (`AdHoc.xcconfig`): no Apple team needed. Passkeys and the shared keychain groups don't work.

Telemetry is opt-in and off unless you tick it during onboarding; leave it unticked.

## Update

Take upstream's changes, run `scripts/fork/build.sh`, quit the app and copy the new `Ardia Fork.app` over the old
one. The profile lives outside the app, so nothing is lost.

## Known gaps

- The `ardia` CLI (`apps/cli`) and the Raycast extension (`extras/raycast-ardia`) still target `com.ardia.browser`.
- The engine's own branding still says `com.ardia.browser` (it's prebuilt), so Chromium's helper processes and its
  "Ardia Safe Storage" keychain item are shared with an official install on the same Mac.
