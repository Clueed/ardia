# The `ardia` command

`ardia` drives a running Ardia from the terminal with Python and [pydoll](https://pydoll.tech) 3.0. It's a separate
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

- `ardia profiles [--json] [--data-dir DIR]` lists every profile from `GET /ardia/profiles?token=CONTROL`: one line
  each, `Work (real)` or `LinkedIn (agent, 2 connected)`, or `{"profiles":[{"name","kind","connected"}]}` with
  `--json` (`kind` `real` or `agent`, `connected` the number of live sessions). Exit 0, or 2 unreachable.
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
  to drive after a restart.
- `ardia disconnect [--session ID] [--data-dir DIR]` (`/ardia/disconnect?token=SESSION`) ends the session and closes
  its sockets; prints `disconnected`.
- `ardia rename NAME [--session ID] [--data-dir DIR]` (`/ardia/rename?token=SESSION&name=NAME`) renames the session's
  agent profile; prints `renamed to NAME`. Exit 1 for `not-agent` (a real profile), `bad-name` or `name-taken`.
- `exec`, `run`, `scripts test`, `disconnect` and `rename` take the session from `--session ID`, else `$ARDIA_SESSION`; there's
  no "most recent" default. `browse` takes it from `--ardia-session ID`, else `$ARDIA_SESSION` (its `--session` is
  agent-browser's session name). On the token path, without one they print one line (`Connect first: run ardia connect
  --new NAME … then pass --session ID or set $ARDIA_SESSION.`) and exit 6. A session Ardia doesn't know (ended by
  `disconnect`, quit, control off or 30 minutes idle, or mistyped) also exits 6 with `That session has ended …`:
  `disconnect` and `rename` get a 404; `exec` and `scripts test` ask `/ardia/active` after the browser socket fails
  to open or drops, and a 404 there means the session, anything else the exit-2 line. `--port`, `--ws` and
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
  `new_tab`), `await pinned()`, `await open_tabs(profile=None)`,
  `await history(days=1, limit=200, profile=None, domains=False)` (see Browsing data), `await run(command, arg=None,
  window=None, tab=None)` (through the gateway with the run's session), `await windows()` and `async for e in events(*names)`
  (over the control socket, no session) (see `docs/automation.md`), `By`, `Key`,
  `asyncio`, pydoll's exports and its common exceptions. It prints the last expression's value. Exit 0 done, 1 the
  code raised or timed out (default 300 s), 2 Ardia can't be reached or closed the browser socket (it watches the
  socket, so turning the setting off ends an idle run at once), 6 no session or it ended, 130 interrupted.
- `ardia browse <command> [args]` takes agent-browser's commands, flags and output against the running Ardia, in the
  session's profile (`--ardia-session ID` or `$ARDIA_SESSION`; see The `ardia browse` command).
- `ardia mcp [--session ID] [--data-dir DIR]` serves the same calls to an MCP client over stdio (see The MCP server).
- `ardia skills install --target general|codex|claude-code|cursor|opencode [--target …] [--project]` installs the
  agent skill (`ardia_cli/skill`: `SKILL.md`, `references/pydoll.md` and `references/browse.md`) into `~/.agents/skills` (general, codex),
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
- `ardia windows` lists the windows and their tabs (see `docs/automation.md`).
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
  each of `run`, `commands`, `windows`, `events` and `on`.

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
`windows()`, `events(*names, full_urls, idle)`, `history(…)`, `pinned()` and `open_tabs(profile)` over the control socket
and the data dir (async). They return plain data and raise one family of errors, each with a `kind` and a `code`:
`Unreachable` (`unreachable`), `OutcomeUnknown` (`outcome_unknown`: the request went out and the connection dropped),
`SessionGone` (`session`: none given, or it ended), `Refused` (`refused`, `code` is Ardia's, like `name-taken` or
`unknown_command`), `Denied` and `Expired`. They subclass the older types, so `exec`'s `CommandError`, `ControlUnreachable`
and `SessionError` still catch them. `connect` withdraws its request (`&cancel=1`) on any exception, Ctrl-C or a signal
included, and remembers the session it got.

The CLI commands (`profiles`, `connect`, `disconnect`, `rename`, `run`, `commands`, `windows`) call it and only format
text and map `kind` to exit codes; `exec`'s `run`, `windows`, `events`, `history`, `pinned` and `open_tabs` are its
methods. `events`, `on` and `hooks` keep their own socket handling (raw lines, drop counts, programs), and `browse` its
daemon.

## The MCP server

`ardia mcp` is a stdio MCP server (JSON-RPC, protocol 2025-06-18, 2025-03-26 or 2024-11-05, whichever the client asks
for) written on the API, with no MCP library (`ardia_cli/mcp.py`). Add it with `claude mcp add ardia -- ardia mcp` or
`codex mcp add ardia -- ardia mcp`. Tools: `profiles`, `connect(name, new, agent)`, `disconnect`, `rename(name)`,
`run(command, arg, window, tab)`, `commands`, `windows`, `wait_for_event(events, timeout ≤ 300 s, full_urls)` (the next
event, or `{timedOut: true}`), `browse(args)`, `history(days, limit, profile, domains)`, `pinned`, `open_tabs(profile)`.
There's no `exec`: a client that can call tools shouldn't get arbitrary Python on the owner's Mac.

- **Session.** The server holds it: from `--session`/`$ARDIA_SESSION` at start, else from `connect`. No tool returns it,
  and every line the server writes is redacted. Tools that need one answer `call connect first` until then. A session
  the server opened with `connect` is disconnected when the client goes away (stdin closes) or connects again; one it
  was given stays open.
- **connect** names the agent from its `agent` argument, else `$ARDIA_AGENT`, else the client's `clientInfo.name`. On one
  of the owner's profiles it sends a `notifications/progress` (`Waiting for the owner to allow it in Ardia`) when the
  client gave a `progressToken`, then waits up to 120 s; `notifications/cancelled` withdraws the request.
- **browse** runs `ardia browse --json ARGS` with the session in the environment (never argv) and returns its `data`;
  a batch returns `{batch: [...]}`.
- **Results.** A tool's data is both `structuredContent` (lists wrapped, like `{profiles: [...]}`) and JSON text. A
  failure is `isError: true` with `{error: kind, code, message}`: the API's kinds, plus `browse` with agent-browser's
  code (`unknown_ref`, `stale_ref`, …). Unknown tools, unknown or missing arguments and wrong types are JSON-RPC
  `-32602`. Calls run concurrently; `ping` answers while one waits.

## The `ardia browse` command

`ardia browse` gives agent-browser's command line (0.35: commands, flags, `@eN` refs, text output with `✓`/`✗`, and
`--json` as `{"success","data","error"}`) on top of the running Ardia, so an agent that knows `agent-browser <args>`
types `ardia browse <args>`. None of agent-browser's code is used. Code: `ardia_cli/browse/` (`cli.py` parses the
globals and runs the commands that need no browser, `daemon.py` owns the connection, `commands.py`, `actions.py`,
`snapshot.py`, `capture.py`, `media.py`, `audit.py`, `react.py`, `vault.py`, `plugins.py`, `readurl.py`).

### Process model

Each session has a background daemon that owns the CDP connection, the refs, the tabs it opened and the tracked
mouse position, so a humanized path starts where the last one ended. `ardia browse` talks to it over a Unix socket.

- Everything lives in `<data dir>/Browse/` (the data dir as `exec` finds it; with `--port` or `--ws`,
  `--data-dir`/`$ARDIA_DATA_DIR`, else the installed app's). The folder is created 0700 and must be a real folder the
  user owns (`O_NOFOLLOW`, checked by `fstat`); every file in it is opened relative to it.
- A session's files are named by `sha256(namespace, endpoint, session)`, never by the session name (on the token path
  the endpoint includes a hash of the ardia session, so each `ardia connect` session gets its own daemon), which must match
  `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`: `<key>.lock`, `<key>.sock`, `<key>.json` (session name, pid) and `<key>.log`
  (the daemon's redacted stderr). The socket is bound and connected by a relative name after `fchdir` into the
  folder, so a long data dir never hits the 104-byte `sun_path` limit.
- The daemon holds an exclusive `flock` on `<key>.lock` for its whole life. Only with that lock held does it treat
  an existing `<key>.sock` as stale and unlink it; it binds with umask 0177 so the socket is 0600 from the start,
  records the socket's inode, and at exit unlinks it only if it's still that inode. Both ends check the other's
  uid with `LOCAL_PEERCRED`; the client also checks the socket is a socket, owned and 0600.
- On the token path the client needs an ardia session (`--ardia-session ID`, else `$ARDIA_SESSION`) before it
  starts or asks a daemon: without one it prints the `Connect first` line and exits 6, like `exec`. The daemon
  connects to the gateway with that session token, so it sees only the session's profile.
- The client starts the daemon (`python -I -c`, its config on stdin, never argv or env) when the socket doesn't
  answer, and waits up to 15 s. A request is one JSON line; the daemon serializes commands, so one gesture never
  interleaves with another, and cancels a command whose client went away (Ctrl-C).
- **Idle disconnect.** After 30 s with no admitted or queued command, no held key or button and no capture lease
  (console or errors, network log, HAR, route, trace, record, stream, init scripts, emulation), the daemon drops the
  CDP connection so the control pill goes away, but keeps its state. The next command reconnects: it re-reads and
  re-checks `ArdiaGateway.json` (or `/json/version`) and refuses, ending the session, if the browser instance
  (the gateway file's `pid:generation:browser path`, or the browser WebSocket path) changed. If the ardia session
  ended meanwhile (`/ardia/active?token=SESSION` is a 404), the command exits 6 with the session-ended line. Admission and the idle check run on one
  event loop under the command lock, so a disconnect never races a command.
- **Connection loss is terminal.** When Ardia closes the connection itself (Stop, control turned off, Ardia quit,
  `ardia disconnect`), the session ends (exit 6 with the session-ended line when the gateway no longer knows the
  ardia session, else exit 2): queued commands fail, nothing reconnects and nothing is replayed. pydoll's `ConnectionHandler`
  is subclassed so it never reconnects on its own, with a 256 MB `max_size`. A link found dead when a command
  starts is treated the same way, before any endpoint is resolved again; only the daemon's own idle disconnect
  reconnects. A command that may already have been dispatched is never retried; it reports that its outcome is
  unknown (exit 2 on connection loss, 1 otherwise). That covers a timeout on any method that changes something
  (`Page.navigate`, `Page.reload`, `Target.createTarget`/`closeTarget`/`activateTarget`, `Input.*`, `Emulation.*`,
  cookie, Fetch and download methods, `eval`, and every isolated-world call that isn't marked as a read), a daemon
  that goes away after taking a mutating command, and batch: after an unknown outcome the rest of the batch isn't
  run and is reported as `not_run`. Isolated-world reads are retried once when the document changes under them;
  writes (`history.go`, `storage set`, `select`, `pushstate`, scripted scrolls) fail with `document_changed` and are
  never replayed on the new document.
- `close` takes the command lock, marks the session closing, and only then closes its tabs; requests already queued
  or arriving later get `session_closing`. On any stop the daemon lets running handlers settle (up to 5 s, then
  cancels them) before it touches the browser. Every answer is sanitized (registered tokens and any `token=` query
  are masked in each JSON field and in the text) before it's written, and the daemon refuses to send an answer over
  256 MB.
- While disconnected the daemon watches `ArdiaGateway.json` every 2 s and exits when it disappears or names another
  instance. It also exits after `--idle-timeout`/`AGENT_BROWSER_IDLE_TIMEOUT_MS` (default 1 h) without commands, and
  on `close`. It takes a lease on its CLI version like `ardia` does.
- Sessions (`--session`, `AGENT_BROWSER_SESSION`, default `default`; `--namespace`) are command-state namespaces on
  the same Ardia, not isolated browsers: cookies, storage and logins are the user's in all of them. A capture or
  route claims its tab in `Browse/claims/` (checked against the owner's lock), and a second live session is refused
  on a tab another one owns. The claim is taken before the CDP domain is enabled (console and errors, including
  `open --capture-console`, network, HAR, route and credentials, trace, record, stream), dropped if enabling fails,
  and released by the matching stop (`har stop`, `unroute` of the last route, `trace`/`profiler stop`,
  `record stop`, `stream disable`) or when the session ends.

### Refs

Refs keep agent-browser's `@eN` form with stable numbers: a node (same browser instance, target, frame, document
and backend node id) keeps its number across snapshots and `find`, so repeat snapshots of an unchanged page give
identical refs. A node seen for the first time takes the next unused number, and a number never moves to another
node, so a delayed `click @e1` can't land on a different element; once its node or document is gone it fails as
stale. Numbers keep rising across documents (a new page's nodes are new nodes), and refs of documents a tab has left
are forgotten. Each ref keeps the browser instance, target id, frame id,
the frame's loader id, the snapshot generation and the backend DOM node id (with role and name for display). A ref
resolves only within that lifetime: the instance must match, the frame must still have the same loader
(`Page.getFrameTree`), and `DOM.resolveNode` must find the node, connected, in the isolated world. Anything else is
`Stale ref @eN: <why>. Run snapshot again` (`code: "stale_ref"`); there's no fallback by role or name. Refs survive
the idle disconnect (backend node ids outlive CDP sessions). `find` gives its element the next ref.

### Input

Humanized input is on by default and goes through pydoll's own classes: `Mouse` (`click`, `dblclick`, `hover`,
`drag`, `mouse move`; Bézier paths with Fitts timing, overshoot and tremor, press and hold timing), `Scroll`
(`scroll`, `scrollintoview`, and scrolling a target into view before a click), and `Keyboard` (`type`, `fill`
(click in, select all, Backspace, then type), `keyboard type`, `press`). pydoll's default timing is kept. Typos are
off: `SteadyKeyboard` overrides `Keyboard._should_make_typo` to return False, and `tests/test_browse.py` fails if a
pydoll update renames it or stops routing humanized typing through it. `keyboard inserttext` stays an instant
`Input.insertText`. `--no-humanize` turns it off for one command, `AGENT_BROWSER_NO_HUMANIZE=1` for the session.
`fill` and `type` follow a field the page swaps out when it's focused (Wikipedia's Vector 2022 search box mounts a new
input on first focus): if the target is detached after the focusing click or `DOM.focus`, and focus sits on an
editable field in the same frame and document that matches it (same tag and type, and a shared id, name, placeholder,
aria-label or title), they type there and report `retargeted: true` (the text output says so too). Anything else
fails with `element_replaced` and types nothing. `auth login` never follows a replacement. Click points get a small
random offset inside the box; a click whose point is covered fails with
`covered by <tag#id.class>`.

Every input command confirms the page got it. Capture listeners in the isolated world count trusted `mousedown`,
`mouseup`, `mousemove`, `keydown`, `keyup` and `wheel` events in the target's frame; after the gesture the command
waits up to 1.5 s for the counts it needs (a click's `mousedown` and `mouseup`, one `keydown` and `keyup` per typed
character, a `wheel` per scroll, a `beforeinput` or `input` for `keyboard inserttext`). If the listeners can't be set
up the command fails before sending anything (`input_unconfirmable`). If none of the events arrive it fails with
`input_not_delivered`; if only some do (a `mousedown` without its `mouseup`), or confirmation fails after sending, it
reports an unknown outcome, since part of the gesture may have landed. A navigation or a closed frame counts as
delivered, and so do keys sent while focus is in an iframe and a raw `mouse` event over one, since those land in
another frame. The listeners add no DOM and nothing the page's world can enumerate.

Held keys and buttons are tracked before each dispatch, and a gesture that's interrupted releases them in a
bounded (2 s), shielded `finally`; `keydown` and `mouse down` stay held across commands on purpose (and keep the
connection up). An interrupted drag reports an unknown outcome. HTML5 `draggable` sources are refused: without
`Input.setInterceptDrags` (gated) a synthetic drag becomes a real macOS drag session.

Chrome doesn't deliver mouse or keyboard input to a hidden tab, and a tab `open` puts in the background is hidden.
Input commands check `document.visibilityState` first and fail with an explanation instead of reporting a click
that never happened. `open --show`, `tab new --show`, `tab <id> --show` or `AGENT_BROWSER_SHOW_TAB=1` show the tab
(`Target.activateTarget`, retried until the page reports visible). `scroll` on a hidden tab keeps pydoll's
humanized timing but applies each step with `scrollBy` in the isolated world; `record` and `stream` refuse a hidden
tab (it paints no frames). Making background tabs take input would need an engine change (for example keeping CLI
tabs visible to the renderer, as a capture does).

### What the page can see

`ardia browse` doesn't change the page's main world by default: locating, snapshots (`Accessibility.getFullAXTree`,
cursor-interactive elements found by computed style), `get`, `is`, `find`, `read`, `storage`, `select`, `pushstate`,
`vitals` (`PerformanceObserver` with buffered entries) and `a11y` (axe-core, `iframes: false`) run in an isolated
world (`Page.createIsolatedWorld`, `ardia-browse`) or through browser-side CDP. `--annotate` lists and labels only the refs whose boxes fall inside the
captured image (agent-browser 0.35.1 prints every ref on the page in its legend; ardia browse lists only what the
image shows), and draws its labels on the
PNG in Python, so nothing is added to the page. The page still sees what a person causes: trusted input events,
focus, scrolling, and the DOM changes those lead to (`select` and `pushstate` dispatch their `input`/`change` and
`popstate` events from the isolated world). Only `eval`, `wait --fn`, init scripts and the React hook run in the
main world. `wait --fn` is the caller's JavaScript like `eval`, so it runs where the page's own globals are; it's
evaluated every 100 ms until it's truthy. There's no `--enable-automation` and no fingerprint spoofing.

The one deviation from agent-browser: the Runtime domain stays off until console or error capture starts (the first
`console` or `errors`, or `open --capture-console`); from then on it's on for that tab for the rest of the session.
`tests/fixtures/browse/probe.html` records `navigator.webdriver`, new window globals, DOM mutations, and the extra
getter reads `Runtime.enable` adds to console arguments (this engine already stringifies each console argument once
without DevTools, so the classic `Error.stack` bait reads positive on every page; the probe counts the reads beyond
that), plus every mouse and key event. The end-to-end test asserts none after open, snapshot, click, fill, get and
screenshot, that the detector does fire once `console` turns Runtime on, and that input was humanized (several
`mousemove`s before `mousedown`, presses over 20 ms, one `keydown`/`keyup` per character with varying gaps, exact
final value).

### Ardia etiquette

`open` without a session tab opens a new background tab in the sidebar (`Target.createTarget` at `about:blank`,
init scripts registered, then `Page.navigate`); later `open`s navigate the session's tab. The user's tabs are only
acted on after `tab <id>` or `tab active` (the page `/ardia/active?token=SESSION` names: the one shown in the
session's profile, token path only; a 404 there exits 6).
`close` and `tab close` close only tabs this session opened; the guard refuses `Browser.close` on every socket, as in
`exec`. `tab list` shows the user's tabs too (minus prewarmed `about:blank` pages); on the token path the gateway shows only
the session profile's tabs, and refuses anything outside that profile with `ardia: … is outside this session's
profile` (exit 1). `alert` and `beforeunload`
dialogs are accepted, as in agent-browser, unless `--no-auto-dialog`. `get cdp-url` refuses any URL that carries a
token or other credentials, however it was chosen (the token path, `--ws`, `$ARDIA_CDP_URL`); it prints only a
plain `--port`/`--ws` URL. After `frame <iframe>`, if that iframe goes away, commands fail with `frame_gone` until
`frame main` or another `frame`, instead of falling back to the main document.

### Gated by the token policy

The engine's ardia-command policy (`ac_cli_token_policy_methods.cc`), behind the gateway, refuses these methods, so on the real connection
these commands fail with exit 1, naming the method and the command (`code: "policy_refused"`, `data.method`). Each is
implemented and works against a plain `--port` test server, so allowing the method is the only change needed.

| Command | Needs |
| --- | --- |
| `cookies get\|set\|clear`, `cookies set --curl` | `Network.getCookies`, `Network.setCookie`, `Network.clearBrowserCookies` |
| `state save\|load` | `Network.getAllCookies`, `Network.setCookies` |
| `set viewport\|device\|geo\|media` | `Emulation.setDeviceMetricsOverride`, `Emulation.setTouchEmulationEnabled`, `Emulation.setUserAgentOverride`, `Emulation.setGeolocationOverride`, `Emulation.setEmulatedMedia` |
| `set offline`, `set headers` | `Network.emulateNetworkConditions`, `Network.setExtraHTTPHeaders` |
| `set credentials`, `network route\|unroute` | `Fetch.enable` (and `Fetch.fulfillRequest`, `failRequest`, `continueRequest`) |
| `upload` | `DOM.setFileInputFiles` |
| `download <sel> <path>`, `wait --download [path]` | `Browser.setDownloadBehavior` (`wait --download` waits for the next download that starts after it; `download` clicks and saves) |
| `highlight` | `Overlay.enable`, `Overlay.highlightNode` |
| `clipboard copy\|paste` | `Input.dispatchKeyEvent` with the `copy`/`paste` editing commands |
| `clipboard read\|write` | `Browser.grantPermissions` |
| `trace start\|stop`, `profiler start\|stop` | `Tracing.start`, `Tracing.end` |
| `record start\|stop\|restart` | `Page.startScreencast` (and ffmpeg on PATH for the WebM) |
| `stream enable` | `Page.startScreencast` |
| `drag` of an HTML5 draggable | `Input.setInterceptDrags` |

On the token path Ardia also strips `Cookie`, `Set-Cookie` and `Authorization` from network events, so
`network requests` and HAR files never contain them.

### Skipped

`connect` and `inspect` (the endpoint is Ardia's; opening DevTools on the user's tab isn't something the command
does), `install`, `upgrade`, `doctor`, `dashboard`, `mcp`, `chat` (Ardia has no AI features), `profiles` (it never
reads browser profiles), `confirm`/`deny` and `--action-policy`/`--confirm-actions`, iOS and Safari (`-p ios`,
`--device`, `swipe`, `tap`), cloud providers (`-p`, `--provider`), and launch options that only mean something when
agent-browser starts its own browser (`--headed`, `--profile`, `--executable-path`, `--extension`, `--args`,
`--user-agent`, `--proxy`, `--proxy-bypass`, `--ignore-https-errors`, `--ca-cert`, `--allow-file-access`,
`--hide-scrollbars`, `--webgpu`, `--engine`, `--restore*`, `--state`, `--auto-connect`, `--allowed-domains`); these
fail with a message saying so. `--headers`, `--color-scheme` and `--download-path` are launch-time too: they point at
`set headers`, `set media` and `download <sel> <path>`. Config files (`~/.agent-browser/config.json`, `./agent-browser.json`) and
`AGENT_BROWSER_PLUGINS` are never read. `read <url>` fetches with Python's `urllib`, so it never touches Ardia.

When the reader of its output goes away early (`ardia browse snapshot -i | head`), it stops writing and exits 141, as a
program killed by SIGPIPE would, without a traceback.

### Captures and bounds

Console messages (1,000 and 16 MB), errors (500 and 16 MB) and network requests (1,000 and 32 MB per tab) are ring
buffers that count what they drop; each record's text is cut at 64 KB, header values at 8 KB and a record's headers at
64 KB. Response bodies are capped at 1 MB for `network request`, 2 MB each and 64 MB in all for a HAR, trace events at
2 million, a request to the daemon at 16 MB and its answer at 256 MB. `network requests` and `har` start capturing
at their first use (`Network.enable`).

`stream enable [--port N] [--input]` (once allowed) binds 127.0.0.1 only, with its own random token in the URL (never
the CDP token), checks `Host` and `Origin` exactly (localhost or 127.0.0.1 on its port, or no Origin; `null` is refused), takes at most
4 clients, and is view-only unless `--input`. Messages follow agent-browser's (`status`, `frame` with `seq` and
`metadata`, `input_mouse`, `input_keyboard`, `input_touch`).

### Auth vault and plugins

`auth save <name> --url <https url> [--origin <url>]... --username <u> [--password-stdin]` takes the password on
stdin or from a no-echo prompt; `--password` is refused. It talks to Keychain only through `/usr/bin/security -i`
with the command written to its stdin, so `ps` never shows the secret, and captures its output privately (non-ASCII
passwords come back hex-encoded, which the metadata records). The item is a generic password, service
`dev.ardia.browse.auth`, account `<name>`, in the login Keychain. Non-secret metadata (url, origins, username,
selectors) is `Browse/auth/<name>.json`, 0600. Each credential is bound to https origins (http only for localhost).
`auth login` checks the tab's committed top-level origin and the field's frame origin against them before typing,
types per character, and stops if the page navigates, the frame's loader or origin changes, or focus leaves the
field. The check runs after each `DOM.focus` has returned (so a page's focus handler has already run) and right
before that character's key events; for a field in an iframe it also checks the top document's focus is on that
frame. `tests/fixtures/browse/auth.html#steal` moves focus into a cross-origin iframe on focus; the end-to-end test
checks no character reaches it. Any process running as the user can read items `/usr/bin/security` created (Keychain lets that tool read its
own items without a prompt), the same boundary as `ArdiaGateway.json`. `ARDIA_BROWSE_KEYCHAIN` points it at another
keychain file, for tests.

`plugin add <npm-name[@version] | owner/repo[#ref]>` pins the exact version (`npm view`) or commit (`git ls-remote`),
installs it with `npm install --ignore-scripts` into `Browse/plugins/<name>/`, and records it in
`Browse/plugins/registry.json`. Plugins run only through `plugin run` or `auth login --credential-provider`, over
agent-browser's `agent-browser.plugin.v1` protocol (one JSON request on stdin: `protocol`, `capability`, `type`,
`request`; one reply on stdout: `protocol`, `success`, `data` or `error`), with `ARDIA_*` and `AGENT_BROWSER_*` removed
from their environment and a 60 s limit.

### Testing it

`python -m unittest discover -s apps/cli/tests` runs the unit tests (`test_browse.py`). The end-to-end test needs a
built app (never `/Applications`):

```sh
ARDIA_BROWSE_E2E_APP=<build>/Ardia.app python -m unittest apps/cli/tests/test_browse_e2e.py
```

It serves `tests/fixtures/browse` on 127.0.0.1, launches one hidden instance with a DevTools port (`ac launch
--no-wait`) and one on the token path (`open -g -n`, `ARDIA_BACKGROUND=1`, control on in `session.json`, JS from Metro on
`$METRO_PORT` or 8081; it runs `ardia connect Personal` and allows it through the dev harness's `acCliConnect`), both under `~/ardia-scratch/browse-impl/e2e`
(`ARDIA_BROWSE_E2E_DIR`), runs the core loop, the probe, `--no-humanize`, the hidden-tab refusal, refs across an idle
disconnect, the gated errors, a service worker starting mid-session, `tab active` through the session and exit 6
without a live session, then closes its sessions and quits both. The token-path half needs Metro (`pnpm dev`).
The a11y command needs `ardia_cli/vendor/axe.min.js`: `build.sh` adds axe-core 4.10.3 (pinned by sha256 and npm's
sha512); from the repo it falls back to `node_modules/axe-core` in a parent folder.

## Browsing data

For daily reports, `exec` has three helpers that read files in Ardia's data dir. They're coroutines that run in a daemon
thread with one 20 s deadline from the call (the session read, the snapshot, every SQLite connection through a
progress handler that aborts past it, row fetching capped at 200,000), so the event loop and the browser socket stay
live (`await history()`; a bare last expression is awaited anyway), `exec --timeout` returns promptly even if a call
is stuck, and the worker deletes its temp snapshot in its own `finally`. At exit a hook sets a closing flag first
(workers check it before making a temp folder and at every backup or copy step), waits up to 1 s for live workers,
then deletes any temp folder still registered. The data dir is the token path's
(`--data-dir`, `$ARDIA_DATA_DIR`, else the installed app's); with `--port`, `--ws` or `$ARDIA_CDP_URL` it's only
`--data-dir` or `$ARDIA_DATA_DIR`, and without one they raise `BrowsingDataError`. All three run the same
`ArdiaGateway.json` checks as the token path first (regular file, owned, 0600, live pid), so they work only while
Ardia runs with control on. None reads cookies, passwords, Login Data or Web Data. They cover the owner's real
profiles whatever profile the session is in, and skip agent profiles (`session.json` profiles with
`"kind": "agent"`): their pins, tabs and history never show up.

- `await pinned()` reads `<data dir>/session.json` (the app's persisted state, `apps/browser/src/state/session/persist.ts`) and returns
  one dict per pin: `title` (custom title first), `url` (else the pinned URL), `pinned_url`, `kind` (`favorite` for a
  tile, `pinned` for a tab in a pinned folder), `folder`, `profile` (its name) and `parked` (pins of a profile no
  window shows, from `parkedPins`). Pins mirrored across windows count once. Incognito profiles are skipped.
- `await open_tabs(profile=None)` reads the same `session.json` and returns one dict per open tab, in window and
  sidebar order: `url` (else the pinned URL; tabs without one are left out), `title` (custom title first), `profile`
  (its name), `pinned` (a favorite or a tab in a pinned folder). Incognito windows and profiles are skipped; a pin
  mirrored across windows counts once, other tabs once per id. `profile` is a profile name or id; an unknown or agent
  one raises `BrowsingDataError` listing the known names. No page is touched.
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
`ardia_cli/bin/esbuild`. About 18 MB; 52 MB installed. `ardia --version` takes about 10 ms; the first `exec` about 1 s while Python writes its
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
filtering in the helpers; the MCP server over a real stdio pipe: tools and schemas, connect with progress, cancel and
exit cleanup, tool errors, no token on the wire):
`uv run --no-project --python 3.13 --with-requirements apps/cli/requirements.lock python -m unittest discover -s apps/cli/tests`.
