# The `ardia` command

`ardia` drives a running Ardia from the terminal: with a bundled, pinned [agent-browser](https://github.com/vercel-labs/agent-browser)
(`ardia browse`, and the `agent_browser_*` tools of `ardia mcp`), and with Python and [pydoll](https://pydoll.tech) 3.0
(`ardia exec`). It's a separate
download, not part of the app bundle. The app ships `install.sh`, and runs it when the user opts in during onboarding
or in Settings ("Let the ardia command control Ardia").

While it's connected, a pill floats over the bottom centre of the page ("ardia is controlling Ardia · Stop"; Stop turns
the setting off). It overlays the page and never resizes it. It shows at the first connection and stays 3 s after the
last one closes, so a burst of commands shows one steady pill; turning the setting off hides it at once. One per
window: the focused pane of a split, the full screen page, or the Peek while one is open
(`apps/browser/src/components/window/CliControlPill.tsx`, `useCliIndicator` in `state/app/cliControl.ts`).

Code: `apps/cli` (`ardia_cli`, `install.sh`, `scripts/build.sh`). Dependencies are pinned with hashes in
`apps/cli/requirements.lock` (regenerate with `uv pip compile requirements.in --python-version 3.13
--python-platform aarch64-apple-darwin --generate-hashes --no-annotate --no-header -o requirements.lock`, then copy
the pins into `pyproject.toml`).

## Commands

- `ardia connect NAME | --new NAME [--agent NAME] [--json] [--data-dir DIR]` asks for a session
  (`/ardia/connect?token=CONTROL&agent=…&profile=NAME`, or `&new=NAME`). The agent name is `--agent`, else
  `$ARDIA_AGENT`, else `agent`; it's self-declared and only shown to the owner. `--new` makes an agent profile with no
  prompt; `NAME` is any existing profile and needs the owner's Allow, so it prints `Waiting for you to allow it in
  Ardia…` on stderr. Then it polls `&request=ID` every 250 ms for at most 120 s. Allowed: stdout gets only the session
  token (with `--json`, `{"session","profile","kind"}`), the one place a token is printed. Exit 1 `no-such-profile`,
  `name-taken` (for `--new`, naming the existing profile as Ardia spells it) or `bad-name` (empty, over 60 characters,
  control characters), each as one plain line; 2 unreachable (also when the control token is unknown, 404); 4 denied;
  5 expired or no answer (past its own 120 s it sends `&cancel=1`); 130 Ctrl-C, 143 SIGTERM and 129 SIGHUP, each after
  sending `&cancel=1` (2 s deadline), so a killed `connect` never leaves the owner's prompt up. A session on an agent
  profile wakes that profile's sleeping tabs (the 8 most recent; Ardia restores tabs asleep), so its pages are there
  to drive after a restart. A tab a session opens in one of the owner's profiles (`new_tab`, `browse open`, `Target.createTarget`)
  goes into a folder named after the agent, with the terminal icon, in that profile's unpinned tabs (one per window,
  agent name and profile; made on its first tab, reused after); an owner's folder that only shares the name is left alone.
- `ardia disconnect [--session ID] [--data-dir DIR]` (`/ardia/disconnect?token=SESSION`) ends the session and closes
  its sockets; prints `disconnected`.
- `ardia rename NAME [--session ID] [--data-dir DIR]` (`/ardia/rename?token=SESSION&name=NAME`) renames the session's
  agent profile; prints `renamed to NAME`. Exit 1 for `not-agent` (a real profile), `bad-name` or `name-taken`.
- `exec`, `run`, `scripts test`, `disconnect` and `rename` take the session from `--session ID`, else `$ARDIA_SESSION`; there's
  no "most recent" default. `browse` takes it from `--ardia-session ID`, else `$ARDIA_SESSION` (its `--session` is
  agent-browser's session name). Without one they print one line (`Connect first: run ardia connect
  --new NAME … then pass --session ID or set $ARDIA_SESSION.`) and exit 6. A session Ardia doesn't know (ended by
  `disconnect`, quit, control off or 30 minutes idle, or mistyped) also exits 6 with `That session has ended …`:
  `disconnect` and `rename` get a 404; `browse` asks `/ardia/active` before it starts agent-browser; `exec` and
  `scripts test` ask it after the browser socket fails to open or drops, and a 404 there means the session, anything
  else the exit-2 line. `--port`, `--ws` and
  `$ARDIA_CDP_URL` need no session and ignore one. All of these find Ardia through `ArdiaGateway.json` (below), with
  the same checks and exit 2.
- `ardia exec [CODE | -] [-f FILE] [--session ID] [--data-dir DIR] [--port N] [--ws URL] [--timeout S] [--json]` runs
  Python with top-level `await`. In scope: `browser` (pydoll `Chrome`), `tab` (from `GET /ardia/active?token=SESSION`
  on the token path: the page shown for the session's profile in the last focused window that shows it, else the
  newest page the session made that's still open, so it holds while the window is covered; `--port`/`--ws` test
  servers fall back to visible and focused, else visible; with no page, as on New Tab, it's a placeholder that raises
  `NoPageTab` on first use), `tabs` (the session's profile only, which the engine enforces; http, https, about, data
  and blob pages, plus what `new_tab` opens, minus
  the New Tab's prewarmed `about:blank`: on the token path every `about:blank` that isn't the active page, on test
  servers the hidden ones),
  `new_tab(url, background=True)` (in the session's profile), `js(expression, tab=None)` (default: `tab`, else the last
  `new_tab`), `await list_tabs(profile=None)` (as `ardia tabs`),
  `await history(days=1, limit=200, profile=None, domains=False)` (see Browsing data), `await run(command, arg=None,
  window=None, tab=None)` (through the gateway with the run's session), and `async for e in events(*names)`
  (over the control socket, no session) (see `docs/automation.md`), `By`, `Key`,
  `asyncio`, pydoll's exports and its common exceptions. It prints the last expression's value. Exit 0 done, 1 the
  code raised or timed out (default 300 s), 2 Ardia can't be reached or closed the browser socket (it watches the
  socket, so turning the setting off ends an idle run at once), 6 no session or it ended, 130 interrupted.
- `ardia browse <command> [args]` runs the bundled agent-browser against the session's profile
  (`--ardia-session ID` or `$ARDIA_SESSION`; see The `ardia browse` command).
- `ardia mcp [--session ID] [--data-dir DIR] [--tools PROFILES]` serves the same calls, and agent-browser's tools, to
  an MCP client over stdio (see The MCP server).
- `ardia skills install --target general|codex|claude-code|cursor|opencode [--target …] [--project]` installs the
  agent skill (`ardia_cli/skill`: `SKILL.md`, `references/agent-browser.md` and `references/pydoll.md`) into `~/.agents/skills` (general, codex),
  `~/.claude/skills`, `~/.cursor/skills` or `~/.config/opencode/skills`; with `--project`, into `./.agents/skills`,
  `./.claude/skills`, `./.cursor/skills` or `./.opencode/skills`. It replaces only its own `ardia` folder.
- `ardia scripts new|test|install|uninstall|list` writes, tests and installs userscripts (see Userscripts).
- `ardia config path|init|get|set|unset|list|edit|check` reads, writes and checks `config.json` (see
  `docs/config.md`, The ardia command). Never needs Ardia running.
- `ardia theme new|use|list|check` makes, picks and checks colour themes (see `docs/config.md`).
- `ardia run COMMAND [ARG] [--window ID] [--tab ID] [--session ID]` runs one of Ardia's commands in the session's
  profile through the gateway's `/ardia/run` route (see `docs/automation.md`); `--tab` targets one tab without focusing
  it; exit 6 without a live session.
- `ardia commands` lists the commands `run` takes (see `docs/automation.md`).
- `ardia tabs [--profile NAME] [--json]` lists everything open, live and without a session (see `docs/automation.md`).
- `ardia events [EVENT…]` streams browser events (see `docs/automation.md`).
- `ardia on EVENT[,EVENT…] -- PROGRAM` runs a program for each event (see `docs/automation.md`).
- `ardia hooks run|install|uninstall|list` runs the hooks in `hooks.json`, at login through a LaunchAgent (see
  `docs/automation.md`). Hook programs inherit the runner's environment, so one that calls `ardia run` needs a session
  like any other caller: `$ARDIA_SESSION` set where the runner starts, or its own `ardia connect`; without one it
  exits 6 and the hook's output in `hooks.log` says so. `command` hooks send `/ardia/run` through the gateway with the
  runner's `$ARDIA_SESSION` (the event's window, and its tab for page commands); without a session, or for a command
  a session refuses, the hook logs why to `hooks.log` and nothing runs. The login LaunchAgent has no session, so its
  command hooks don't run.
- `ardia --version`, `ardia --help`, `ardia exec --help`, `ardia scripts <command> --help`,
  `ardia config <command> --help`, `ardia theme <command> --help`, `ardia hooks <command> --help` and `--help` on
  each of `run`, `commands`, `tabs`, `events` and `on`.

`exec` never quits Ardia: it refuses `browser.stop()`, and every WebSocket it opens checks each outgoing message (and
refuses fragmented sends), so
`Browser.close`, `Browser.crash` and `Browser.crashGpuProcess` never leave the process, whether sent one at a time, in
an `execute_commands` batch (checked whole before anything is sent) or straight on the socket. On exit (normal, an
exception or Ctrl-C) it closes only its own page and browser WebSockets. Its WebSockets always connect directly,
ignoring `http_proxy`, `ws_proxy` and the like, so no proxy sees the token.

## One API under the CLI and the MCP server

`ardia_cli/api.py` is the only layer that talks to Ardia for the session, automation and browsing-data calls. `Ardia(root,
session)` (or `Ardia.at(data_dir, session)`) has `profiles()`, `connect(name, new, agent, on_waiting, sleep)`,
`disconnect()`, `rename(name)` and `run(command, arg, window, tab)` over the gateway (blocking), and `commands()`,
`tabs(profile)`, `events(*names, full_urls, idle)` and `history(…)` over the control socket
and the data dir (async). They return plain data and raise one family of errors, each with a `kind` and a `code`:
`Unreachable` (`unreachable`), `OutcomeUnknown` (`outcome_unknown`: the request went out and the connection dropped),
`SessionGone` (`session`: none given, or it ended), `Refused` (`refused`, `code` is Ardia's, like `name-taken` or
`unknown_command`; the profile refusals carry a sentence, and `name-taken` names the profile as Ardia spells it),
`Denied` and `Expired`. They subclass the older types, so `exec`'s `CommandError`, `ControlUnreachable`
and `SessionError` still catch them. `connect` withdraws its request (`&cancel=1`) on any exception, Ctrl-C or a signal
included, and remembers the session it got.

The CLI commands (`connect`, `disconnect`, `rename`, `run`, `commands`, `tabs`) call it and only format
text and map `kind` to exit codes; `exec`'s `run`, `list_tabs`, `events` and `history` are its methods. `events`, `on`
and `hooks` keep their own socket handling (raw lines, drop counts, programs). `browse` and the MCP server's
`agent_browser_*` tools hand the session to agent-browser (`ardia_cli/agent_browser.py`: the binary, its
environment, the refused flags and stopping its daemon).

## The MCP server

`ardia mcp` is a stdio MCP server (JSON-RPC, protocol 2025-11-25, 2025-06-18, 2025-03-26 or 2024-11-05, whichever the
client asks for) written on the API, with no MCP library (`ardia_cli/mcp.py`). Add it with `claude mcp add ardia --
ardia mcp` or `codex mcp add ardia -- ardia mcp`. Its own tools: `connect(name, new, agent)`, `disconnect`,
`rename(name)`, `run(command, arg, window, tab)`, `commands`, `tabs(profile)`, `wait_for_event(events, timeout ≤ 300 s,
full_urls)` (the next event, or `{timedOut: true}`), `history(days, limit, profile, domains)`. After them come
agent-browser's typed tools (`agent_browser_open`, `_snapshot`, `_click`, `_fill`, …), forwarded to the bundled
agent-browser. There's no `exec`: a client that can call tools shouldn't get arbitrary Python on the owner's Mac.

- **Session.** The server holds it: from `--session`/`$ARDIA_SESSION` at start, else from `connect`. No tool returns it,
  and every line the server writes is redacted. Tools that need one answer `call connect first` (kind `session`) until
  then. A session the server opened with `connect` is disconnected when the client goes away (stdin closes, SIGTERM or
  SIGHUP) or connects again; one it was given stays open.
- **connect** names the agent from its `agent` argument, else `$ARDIA_AGENT`, else the client's `clientInfo.name`. On one
  of the owner's profiles it sends a `notifications/progress` (`Waiting for the owner to allow it in Ardia`) when the
  client gave a `progressToken`, then waits up to 120 s; `notifications/cancelled` withdraws the request.
- **Forwarded tools.** `ardia_cli/agent_browser_tools.json` is agent-browser's `tools/list` (every page) for each
  tools profile, generated from the pinned binary by `scripts/agent-browser-tools.py`; `build.sh` fails when it doesn't
  match. They're listed before `connect`, so clients that ignore `listChanged` see them. `--tools` picks the profiles
  (`core` by default; `core,tabs,debug`, `all`) and is passed on. One deny list in `mcp.py` drops the tools that
  install, upgrade, diagnose, connect elsewhere, open a dashboard or DevTools, chat (no AI features), confirm or deny,
  list profiles, sessions or plugins, serve skills (the ardia skill does) or print the CDP URL; the arguments that
  would pick another agent-browser session or namespace, close every session, or set domains, CAs, idle time or
  restore state are removed from every schema and refused as unknown. `extraArgs` carrying `--cdp`,
  `--auto-connect`, `--config`, `--session` or `--namespace` is refused (`refused_argument`); agent-browser itself
  also refuses host-changing flags there.
- **The child.** The first forwarded call after `connect` starts `agent-browser mcp --tools <profiles> --config
  ardia_cli/agent-browser.json` with the same environment as `ardia browse` (below), so a session that only uses
  `tabs` or `run` starts nothing. Calls go to it with the server's own ids; the reply comes back as it is, redacted.
  `notifications/cancelled` is passed on, and so is its `notifications/progress` (the client's `progressToken`
  travels in `_meta`). Requests from the child get `-32601` (`ping` an empty result). A call waits for its
  `timeoutMs` (default 120 s) plus 30 s. When the child dies, its call fails (`agent_browser`) and the next one starts
  it again. It's stopped (stdin closed, then SIGTERM and SIGKILL, 2 s apart) on `disconnect`, on `connect` to another
  session, when its session ends and when the server exits, and then its daemon (the pid in
  `<socket dir>/<session name>.pid`, checked to be an `agent-browser`) gets SIGTERM, then SIGKILL after 2 s.
- **Ended sessions.** When a forwarded call fails (an error result, or the child gone or silent) the server asks
  `/ardia/active`; if the session is gone, or Ardia is, the answer is the `session` error with the session-ended line,
  and the child stops. Never a retry.
- **Results.** Our tools' data is JSON text only, with no `structuredContent`: Claude Code shows the model only
  `structuredContent` when both are present, and none of them declares an `outputSchema`. A failure is `isError: true`
  with its sentence as text and `{error: kind, code, message}` as `structuredContent`: the API's kinds, plus
  `agent_browser` and `refused_argument`. Forwarded results are agent-browser's. Unknown tools, unknown or missing
  arguments and wrong types are JSON-RPC `-32602`. Calls run concurrently; `ping` answers while one waits.

## The `ardia browse` command

`ardia browse <args>` runs the bundled agent-browser (`ardia_cli/bin/agent-browser`, 0.41.2, pinned in `build.sh`) on
the session, so its commands, refs and output are upstream's; `ardia browse skills get core` prints its own
version-matched guide (`ardia_cli/skill-data`). It's `ardia_cli/agent_browser.py`: it takes `--ardia-session ID`
(else `$ARDIA_SESSION`) and `--data-dir DIR` out of the arguments, resolves the session's address from
`ArdiaGateway.json`, checks `/ardia/active`, and `execve`s the binary. Without a session it exits 6 with the connect
first line (only `--version`, `--help` and `skills` run without one); an ended one exits 6, an unreachable Ardia 2.
The environment carries the session, never argv:

- `AGENT_BROWSER_CDP=ws://127.0.0.1:<gateway port>/devtools/browser/<id>?token=<session>`;
- `AGENT_BROWSER_SESSION=<sha256(session)[:16]>`, so each ardia session gets its own daemon;
- `AGENT_BROWSER_NO_VERSION_CHECK=1`, and `AGENT_BROWSER_CONFIG=ardia_cli/agent-browser.json`, a trusted config of
  ours (idle timeout 30 m, since a daemon on an external browser otherwise never idles out), so no `~/.agent-browser`
  or `./agent-browser.json` config is read;
- inherited `AGENT_BROWSER_AUTO_CONNECT`, `_PROVIDER`, `_CDP_HEADERS` and `_NAMESPACE` are dropped.

`--cdp`, `--auto-connect`, `--config` and `get cdp-url` (the address carries the token) are refused with exit 64.
`$ARDIA_AGENT_BROWSER` points it at another binary (a repo checkout has none in `ardia_cli/bin`; tests use a fake).
The gateway's policy refuses what agent-browser needs for `cookies`, `state save|load`, `set
viewport|device|geo|media|offline|headers|credentials`, `network route`, `upload`, `download`, `clipboard`, `trace`,
`profiler`, `record` and `stream`; they fail with `ardia: <Method> isn't allowed for the ardia command`. In a tab
the app opens in the background, clicks and keys don't arrive (`click` prints `✓ Done`); `fill` works.

## Browsing data

For daily reports, `exec` has `history()`, which reads files in Ardia's data dir (pins and open tabs come live
from `list_tabs()`, see `docs/automation.md`). It's a coroutine that run in a daemon
thread with one 20 s deadline from the call (the session read, the snapshot, every SQLite connection through a
progress handler that aborts past it, row fetching capped at 200,000), so the event loop and the browser socket stay
live (`await history()`; a bare last expression is awaited anyway), `exec --timeout` returns promptly even if a call
is stuck, and the worker deletes its temp snapshot in its own `finally`. At exit a hook sets a closing flag first
(workers check it before making a temp folder and at every backup or copy step), waits up to 1 s for live workers,
then deletes any temp folder still registered. The data dir is the token path's
(`--data-dir`, `$ARDIA_DATA_DIR`, else the installed app's); with `--port`, `--ws` or `$ARDIA_CDP_URL` it's only
`--data-dir` or `$ARDIA_DATA_DIR`, and without one it raises `BrowsingDataError`. It runs the same
`ArdiaGateway.json` checks as the token path first (regular file, owned, 0600, live pid), so it works only while
Ardia runs with control on. It reads no cookies, passwords, Login Data or Web Data. It covers the owner's real
profiles whatever profile the session is in, and skip agent profiles (`session.json` profiles with
`"kind": "agent"`): their history never shows up.

- `await history(days=1, limit=200, profile=None, domains=False)` reads Chromium's `History` for each real profile's
  folder under `<data dir>/Chromium/` (`Default` for data id `default`, else `Profile <dataId>`; folders no real
  profile in `session.json` names, agent ones included, are skipped, and without a `profiles` map only `Default` is
  read; never incognito, guest or system profiles; `profile` must be a profile name or one of those folder names,
  never a path). Rows per URL, newest first: `url`, `title`, `visits` in
  the window, `total_visits`, `last_visit` (ISO 8601, local time), `profile`. Only http(s) pages; subframe
  navigations and hidden URLs are left out. `domains=True` rolls rows up per domain (`domain`, `visits`, `pages`,
  `last_visit`, `top_title`, `profile`), most visited first. It never touches the live file for writing: it opens it
  read-only (`mode=ro`) and copies it with SQLite's backup API into a private temp dir; the progress callback ends
  the backup once 0.5 s have passed. Chromium keeps `History` exclusively locked while Ardia runs, so that usually
  fails, and it falls back to copying `History` plus its `-wal`/`-journal` (no symlinks, regular files only), checking
  the copy opens, up to 3 tries. A copy taken mid-write can miss the last few visits. The copy checks the deadline
  between 1 MB chunks.

## Userscripts

`ardia scripts` runs Violentmonkey-style userscripts written in TypeScript or JavaScript. A `.user.js` from
Violentmonkey or Tampermonkey works as is. Keys read from the `// ==UserScript==` block: `@name` (the id is its slug),
`@namespace`, `@version`, `@description`, `@match`/`@exclude-match` (Chrome match patterns for content scripts:
`*`, `http`, `https`, `file`, `ftp` schemes, checked when parsed the way `URLPattern::Parse` does, a bit stricter:
hosts canonicalized as the browser does: lowercase, IDN to punycode (refused when it has ß, ς or a joiner, which
IDNA versions treat differently), WHATWG IPv4 forms like `127.1` or `2130706433` to dotted, compressed IPv6, no `%`
anywhere (so no IPv6 scope ids); ports 0 to 65535 without leading zeros and none with scheme `*`),
`@include`/`@exclude` (globs over the whole URL with `base::MatchPattern`: `*` any run, `?` zero or one character,
`\` escapes, matched left to right without backtracking; regexes are refused),
`@run-at` (`document-start`, `document-end` default, `document-idle`), `@inject-into` (`page` default and `auto` run
in the page's world, `content` in an isolated world), `@noframes`. `@grant` other than `none`, `@require` and
`@resource` are ignored with a warning. `@match` and `@include` add up, as in Violentmonkey.

Builds go through esbuild: `--bundle --format=iife --platform=browser --target=chrome130 --tsconfig-raw={}`, not
minified, so relative imports bundle in and no `tsconfig.json` is read (no `paths` aliases). Types are stripped, not
checked. Every input esbuild reports in its metafile must be a `.ts .tsx .mts .cts .js .jsx .mjs .cjs .css` source
(JSON, text and other loader types are refused), a regular file with no other hard links, and inside the script's
own folder tree; nothing may come from Ardia's data dir (the `--data-dir`/`$ARDIA_DATA_DIR` one and the installed
app's), even inside the tree. Both are decided by file identity (`st_dev`, `st_ino` of each ancestor after
resolving symlinks), not by path spelling, since APFS is case-insensitive. A script directly in the home folder or
`/` may import nothing. Otherwise the build fails
before anything is injected or published, so a script can't bundle `ArdiaGateway.json`, `ArdiaControl.json` or other files and send
them to a page. `data:` imports are allowed. The tarball ships esbuild in `ardia_cli/bin/esbuild` and an installed
CLI uses only that one; from the repo (`python -m ardia_cli`) it falls back to
`node_modules/@esbuild/darwin-arm64/bin/esbuild` in a parent folder of the package, then `esbuild` on PATH. It never
looks in the cwd.

- `ardia scripts new NAME [--match PATTERN]…` writes `NAME.user.ts` in the cwd (default match
  `https://example.com/*`), never over an existing file.
- `ardia scripts test FILE [--url URL] [--expect JS] [--wait S] [--screenshot PATH] [--keep] [--json] [--session ID]
  [--data-dir DIR] [--port N] [--ws URL]` finds Ardia like `exec` (same exit 2 and 6, same session), opens its own
  background target in the session's profile at `about:blank`,
  attaches a flat session, turns on Runtime and Page, registers the script with `Page.addScriptToEvaluateOnNewDocument`
  (no `worldName`: the token policy refuses named worlds), and only then navigates to `--url` (default: the first
  `@match` whose host has no wildcard, path up to its first `*`). The registered source is a wrapper around the
  build that applies the `@match`/`@include`/excludes rules, `@noframes` and `@run-at` like the extension would, and
  reports start/skip/done through `console.debug` with a random marker. Matching is a port of Chromium's
  `URLPattern::MatchesURL` (`extensions/common/url_pattern.cc`) and `base::MatchPattern` (`base/strings/pattern.cc`)
  in both the wrapper and Python: canonical hosts without trailing dots (`*.` takes subdomains, never of IP
  addresses), the effective port (`:443` matches `https://example.com/`; no port matches any), the path plus query
  unescaped by `UnescapeURLComponent`'s `NORMAL` rule, including its full list of characters left escaped (BiDi
  controls, spaces, default-ignorable and format characters, lock emoji) (`/café/*` matches `/caf%C3%A9`), with a
  raw fallback, and `/foo/*`
  matching `/foo`. `apps/cli/tests` runs both against cases taken from `url_pattern_unittest.cc` and
  `pattern_unittest.cc`, and they agreed with a real Ardia on the glob and percent-encoding cases. Console output and uncaught exceptions count
  as the script's when a stack frame is the script's `sourceURL`; positions map back to the sources through esbuild's
  source map. Cross-origin iframes are reached by `Target.setAutoAttach` with `waitForDebuggerOnStart`, on the token
  path too: the token policy attaches a web frame while it waits to commit, so the script runs at its document start.
  Frames that show an extension's page (a password manager's inline menu, say), a `chrome://` or DevTools page are
  never attached over the token path; a frame that starts loading one cuts off the page's session, as Chrome does for
  `chrome.debugger`. The report says how many iframes never reported. After the top frame ran (or skipped) and the page loaded (at most 10 s
  more, 30 s in all), it listens `--wait` seconds (default 2; Chrome reports unhandled rejections about a second
  late), retrying `--expect` every 100 ms until `Boolean(value)` is true in the page (the report shows the value too). A
  first pass that starts and never finishes, in any frame, fails the test; when the top frame's doesn't finish in 30 s
  the test stops there. Then, in a bounded cleanup, it removes the registration and
  closes the target it made, unless `--keep`. `@inject-into content` is tested in the page's world, with a warning.
  Exit 0 ran without uncaught exceptions and `--expect` truthy, 1 otherwise, 2 Ardia unreachable, 6 no session or it
  ended.
- `ardia scripts install FILE [--data-dir DIR]`, `ardia scripts uninstall NAME [--data-dir DIR]` (by `@name` or id),
  `ardia scripts list [--json] [--data-dir DIR]`. Install and uninstall need control on (the `ArdiaGateway.json`
  checks, else the exit-2 line); list doesn't, and repairs only a named data dir or one with a live gateway file.

### Install contract with the app

The data dir is `--data-dir`, else `$ARDIA_DATA_DIR`, else `~/Library/Application Support/com.ardia.browser`.

1. The CLI takes an exclusive `flock` on `<data dir>/Scripts/.lock` (polled, 30 s deadline). The app takes a shared
   one while it reads and validates. `Scripts/`, `Scripts/scripts/`, record folders and `extension/` must be real
   folders the user owns: each is opened with `O_NOFOLLOW`, and everything below works relative to those folder
   descriptors (`renameatx_np`, `openat`, `rmtree(dir_fd=)`), so a planted symlink is refused, not followed.
2. It keeps its record in `Scripts/scripts/<id>/`: `meta.json` (the parsed metadata, `id`, `world`, `source_file`,
   `installed_at`, `updated_at`), `script.js` (the build) and `source.<ext>` (a copy of the entry file). A new record
   is staged in a temp sibling and only swapped in after the extension built from it validated and was published; if
   that swap fails, the previous extension is swapped back.
3. It regenerates `Scripts/extension/` in a temp sibling: `manifest.json` with only `manifest_version` 3, `name`
   "Ardia Scripts", `version` (`1.<generation / 65536>.<generation % 65536>`), `description` and `content_scripts`;
   `js/<id>.js`; and `generation`. Each content script entry has exactly `matches`, `exclude_matches`,
   `include_globs`, `exclude_globs`, `js`, `run_at`, `all_frames` (false with `@noframes`) and `world` (`MAIN` or
   `ISOLATED`). The whole manifest is checked (keys, every pattern and glob, files, values) before it's published, so
   one bad script can't make the shared extension unloadable, along with the engine's limits: at most 256 content
   script entries, 256 files per entry, 512 distinct files, and a 256 KB manifest. A script with `@match` gets one entry; one with `@include` gets an entry with `matches` `*://*/*` and
   the globs, excluding its `@match` patterns so no page runs it twice. Entries follow install order. When
   `extension/` exists the new folder replaces it with `renamex_np(RENAME_SWAP)` and the old one is deleted, so the
   path never goes missing; a plain rename only when there's none. With no scripts left, `extension/` is removed.
4. It writes `Scripts/generation` (temp file and rename): one more than the largest of `Scripts/generation`,
   `extension/generation` and the last reported one. A crashed run is repaired by the next install or
   uninstall (they rebuild from the records) or `list`: when its data dir was named (`--data-dir`,
   `$ARDIA_DATA_DIR`) or has a live control file, it takes the lock, rebuilds the extension from the records if
   they disagree (`manifest.json` entries, the `js/` files and their bytes), and otherwise publishes
   `Scripts/generation = extension/generation` when the extension is ahead, rebuilds when it is behind, and
   publishes the next generation when there are no records and no `extension/` but `status.json` still reports the
   current generation as loaded. Uninstalling the last script writes `Scripts/generation` before it removes
   `extension/`, so a crash between them looks like an old extension, not a finished uninstall. `list --json` puts
   any repair in its `repaired` key, never ahead of the JSON. `scripts test` never writes to any `Scripts/` folder,
   and nothing creates `Scripts/` under a data dir that wasn't named or live. `extension/generation` holds the same number. A bumped generation with
   no `extension/` means every script was uninstalled.
5. It drops the lock, then polls `Scripts/status.json` for up to 10 s: `{"generation": N, "profiles": {"<profile>":
   {"ok": true} | {"error": "…"} | {"disabled": true} | {"removed": true}}}`; `removed` means no scripts are left and the extension is gone from that profile. Exit 0 when every profile loaded or is turned off, 1 on any
   error, 3 when Ardia didn't report in 10 s (the outcome is unknown; it may still be loading), and 0 with "loads on
   its next launch" when Ardia quit or turned control off while it waited. A newer generation in `status.json` means
   another change replaced this one, and its result is printed.

## How it finds Ardia

1. `--ws URL`, a browser WebSocket URL.
2. `--port N`, a plain DevTools server on 127.0.0.1 (`/json/version`). For test servers only.
3. `$ARDIA_CDP_URL`, like `--ws`.
4. `<data dir>/ArdiaGateway.json`, with `--data-dir` or `$ARDIA_DATA_DIR`, else the installed app's
   `~/Library/Application Support/com.ardia.browser/ArdiaGateway.json`.

The token path talks to the app's gateway, not the engine. The gateway is a small server in ArdiaCore's native code
(`packages/ardiacore`), on a random free 127.0.0.1 port Q, started and stopped with the setting. It sits in front of
the engine's token server: it reads `Chromium/ArdiaControl.json` itself, opens its own upstream sockets with the
engine token, and narrows the engine's policy (method allowlist, web-only targets, header stripping) to one profile
per session. It writes `<data dir>/ArdiaGateway.json` (temp file and rename, deleted on stop and at quit):
`{"port":Q,"browser":"/devtools/browser/<random id>","token":"…","pid":…,"generation":N}`. The CLI opens it without
following links and trusts it only when it's a regular file the user owns, mode 0600, and `pid` is alive. Its `token`
is the control token, new on every start: the gateway takes it only on `/ardia/profiles` and `/ardia/connect`, never
on a WebSocket or `/ardia/active`. Everything else uses the session token from `connect` (`[\x21-\x7e]{16,1024}`,
else the session-ended line): `exec` connects to `ws://127.0.0.1:Q<browser>?token=<session>`; pydoll keeps the query
on every `/devtools/page/<id>` URL, so page sockets carry it too. The gateway scopes those sockets to the session's
profile: targets listed, attached, reported and closed there only, `Target.createTarget` answered by the app opening
a tab in that profile, page sockets to other targets refused at the handshake.

`GET /ardia/run?token=SESSION&command=NAME[&arg=<JSON>][&window=<id>][&tab=<id>]` runs a command scoped to the session's profile
(`docs/automation.md`): `{"result":{"ok":true}}`, or `{"error","message"}` with the socket's codes (`bad_request`
400, `unknown_command` 404, `refused` 403, `no_window` 409, `failed` 500, also when the app doesn't answer in 30 s);
a 404 without a body is an unknown or ended session. The CLI waits up to 35 s for it.

The routes are `GET http://127.0.0.1:Q/ardia/<route>?token=…&…` with every value percent-encoded, a JSON body, and
errors as 4xx `{"error": "<code>"}` (400 `bad-name`, 404 `no-such-profile` or an unknown token, 409 `name-taken`,
403 `not-agent`, 429 `too-many-requests`); a 404 without a code is an unknown token (exit 2 for the control token, 6
for a session). The CLI calls them directly (no proxy, no Origin header, which the gateway refuses, 5 s timeout) with
tokens redacted like everywhere else. The active-page route `/ardia/active?token=<session>` answers
`{"targetId": "<id>"}`, or `{"targetId": null}` when New Tab or an Ardia view is showing; when it fails, `exec` falls
back to the visibility check.

Known weakness, accepted: the engine still writes its own all-access token to `<data dir>/Chromium/ArdiaControl.json`
(same shape, 0600), and anything that can read that file can skip the gateway and its profile scope. The threat model
is careless or prompt-injected agents driving Ardia through `ardia`, not processes with direct file access, so this
is outside it. The CLI never reads that file.

A missing, stale or unsafe gateway file, or a refused connection, prints one line and exits 2:
`Ardia isn't running, or "Let the ardia command control Ardia" is off in Settings.` There's no port scanning and no
`/json` fallback on this path. Neither token reaches the output (both are registered the moment they're read, the
session one before anything connects), except the session token `connect` prints as its result, written past the
redaction: stdout and stderr are redacted as a stream (a token
split across writes is held back until it's complete), and so are log records and everything a logging handler
formats, tracebacks included. pydoll's loggers stay at ERROR. The stream holds back only a tail that could start a
registered token and releases everything on `flush()`, at exit and on SIGTERM or SIGHUP (exit 143). A token printed in
two parts with an explicit flush between them gets through; that gap is accepted.

## Install and upgrade

The app runs `install.sh` with its own environment minus every `ARDIA_*` variable, plus `ARDIA_CLI_HOME`,
`ARDIA_CLI_BIN_DIR` and `ARDIA_CLI_URL` from its `ARDIA_INSTANCE` keys `cliHome`, `cliBinDir` and `cliUrl`
(`CliInstaller.swift`).

`install.sh [--version V] [--sha256 DIGEST] [--uninstall]` (run with `/bin/sh`; `--help`):

- Downloads `https://github.com/mantrakp04/ardia/releases/download/v<V>/ardia-cli-<V>-macos-arm64.tar.gz` (https only)
  into a private temp dir; it runs on Apple silicon only and stops with an error anywhere else. Without `--version` it
  takes the latest release that has the asset. `--sha256` is the only
  digest it trusts (the app passes `Ardia.app/Contents/Resources/ardia-cli.sha256`, which the signed bundle pins), and
  a download needs it: a `.sha256` from the same release would only prove the tarball came from wherever the tarball
  came from. Only a `file://` `ARDIA_CLI_URL` (tests) may go without it, reading `<url>.sha256`. A Debug build has no
  pinned digest, so it installs only that way.
- Verifies the digest, refuses entries outside `ardia-cli-<V>/`, `..` paths, hard links and links pointing outside the
  tree, plus names with control characters, backslashes or ` -> `, extracts to `$ARDIA_CLI_HOME/<V>.partial`, checks
  the extracted tree again (`find`, no line parsing), renames it to `<V>`, and swaps `current` atomically.
- It keeps the current and the previous version, and any version a running `ardia` uses: `ardia_cli` writes
  `<V>/.leases/<pid>` when it starts (from the launcher or `python -m ardia_cli`) and removes it at exit. A lease
  counts only while a process with that pid runs and started no later than the lease was written (`ps -o lstart`
  against the lease's mtime), so a reused pid doesn't pin a version.
- Links `$ARDIA_CLI_BIN_DIR/ardia` (default `~/.local/bin`) to `current/bin/ardia`. It replaces only a link that
  already points into `$ARDIA_CLI_HOME` and refuses anything else. With the default bin dir off the login shell's
  PATH, it adds `export PATH="$HOME/.local/bin:$PATH"` to `~/.zprofile` once.
- A version that is already current is a no-op. Two runs never overlap: each takes a flock on
  `$ARDIA_CLI_HOME/.lock` through fd 9 (`/usr/bin/lockf -s -t 120 9`). The kernel drops it when the run exits, even on
  SIGKILL; a run that waits 120 s prints `error another install is still running`. Uninstall leaves the empty `.lock`
  file, since deleting a lock file other runs may have open would split the lock.
- Output for the app, one line each: `step resolve|download|verify|install|link`, `version <v>`, `path <rc file>`,
  then `installed <bin path>` or `uninstalled`, or `error <message>` with exit 1.

`$ARDIA_CLI_HOME` defaults to `~/Library/Application Support/Ardia/CLI`. The installed version is
`basename "$(readlink "$ARDIA_CLI_HOME/current")"`; the app reads that link to decide whether to upgrade, and after an
app update it runs `install.sh --version <app version> --sha256 <pinned digest>` in the background. The CLI never
updates itself.

## Build and release

`apps/cli/scripts/build.sh <version> <out dir>` writes `ardia-cli-<version>-macos-arm64.tar.gz` and its `.sha256`:
python-build-standalone CPython 3.13 (release and sha256 pinned in the script), the locked dependencies and
`ardia_cli` in its site-packages, pruned of tests, idlelib, Tk, ensurepip, the unused libpython dylib and
`__pycache__`, plus `bin/ardia`, an sh launcher that resolves its links and runs `python3 -I -m ardia_cli`, and
esbuild (the npm `@esbuild/darwin-arm64` tarball, version, sha256 and sha512 pinned in the script) in
`ardia_cli/bin/esbuild`, and agent-browser (the npm `agent-browser` tarball, pinned the same way: its
`bin/agent-browser-darwin-arm64` as `ardia_cli/bin/agent-browser`, its `skill-data` and `LICENSE`). The build checks
`agent-browser --version` against the pin and regenerates the forwarded tool list to compare it with the committed
one. About 26 MB; 72 MB installed. `ardia --version` takes about 10 ms; the first `exec` about 1 s while Python writes its
bytecode cache, later ones about 0.15 s.

`scripts/release.sh` builds it into the release's dist dir after the export and writes its digest to
`Ardia.app/Contents/Resources/ardia-cli.sha256` before the app is signed. The release skill's `publish.sh` uploads the
tarball and its `.sha256`.

## Test

Never against the real home. A hidden instance's plain DevTools port works with `--port`:

```sh
scripts/agent/ac launch <Ardia.app> --data /tmp/ardia-cli-test --onboarded
ardia exec --port <port> 't = await new_tab("https://example.com"); await t.title()'
scripts/agent/ac quit /tmp/ardia-cli-test
```

The `ArdiaGateway.json` path needs the app's gateway and the engine's token server behind it: Chrome's plain server accepts `?token=` on the browser
socket but answers 500 on page sockets with a query. For the installer:

```sh
apps/cli/scripts/build.sh 0.0.1 /tmp/ardia-cli-out
HOME=/tmp/ardia-cli-home ARDIA_CLI_URL=file:///tmp/ardia-cli-out/ardia-cli-0.0.1-macos-arm64.tar.gz \
  /bin/sh apps/cli/install.sh
HOME=/tmp/ardia-cli-home ardia skills install --target claude-code
```

`ardia scripts test` needs a running instance; it reaches cross-origin iframes on both paths, and over `--port` also frames that show an extension's page. Install and the
helpers need the token path: an instance launched without `ARDIA_REMOTE_DEBUGGING_PORT` (the app doesn't start its
control server when the port switch is set) and with control on, for example a scratch dir whose `session.json` has
`"settings": {"cliControl": true}`, opened with `open -g -n --env ARDIA_BACKGROUND=1 --env ARDIA_DATA_DIR=<dir>`.
Unit tests (matching parity with node, import confinement, store rollback and recovery, symlink refusal; config
and theme commands against hand-written schemas in `tests/fixtures` that use every keyword of the subset; connect
allowed, denied, expired and cancelled, session refusal and redaction against a fake control server, agent-profile
filtering in the helpers; the MCP server over a real stdio pipe: tools and schemas, the deny list, connect with
progress, cancel and exit cleanup, tool errors, no token on the wire, and forwarding to a fake agent-browser that
records its argv and environment, stopped on disconnect and exit; `ardia browse` against the same fake):
`uv run --no-project --python 3.13 --with-requirements apps/cli/requirements.lock python -m unittest discover -s apps/cli/tests`.
