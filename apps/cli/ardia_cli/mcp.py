import asyncio
import json
import os
import signal
import sys
import threading
from pathlib import Path

from ardia_cli import __version__, agent_browser, endpoint
from ardia_cli.api import Ardia, ArdiaError, Expired, SessionGone
from ardia_cli.redact import add_secret, redact

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
FORWARDED_TOOLS = Path(__file__).resolve().parent / "agent_browser_tools.json"
DENIED_TOOLS = frozenset({
    "agent_browser_tools_profiles", "agent_browser_install", "agent_browser_upgrade", "agent_browser_doctor",
    "agent_browser_connect", "agent_browser_dashboard_start", "agent_browser_dashboard_stop", "agent_browser_chat",
    "agent_browser_confirm", "agent_browser_deny", "agent_browser_profiles", "agent_browser_skills_list",
    "agent_browser_skills_get", "agent_browser_skills_path", "agent_browser_get_cdp_url", "agent_browser_inspect",
    "agent_browser_plugin_add", "agent_browser_plugin_list", "agent_browser_plugin_show", "agent_browser_plugin_run",
    "agent_browser_session", "agent_browser_session_list", "agent_browser_session_id", "agent_browser_session_info",
})
DROPPED_ARGUMENTS = frozenset({
    "session", "namespace", "all", "allowedDomains", "caCert", "clearCaCert", "useSystemCa", "idleTimeout",
    "restore", "restoreSave", "restoreCheckFn", "restoreCheckText", "restoreCheckUrl",
})
REFUSED_EXTRA_ARGS = agent_browser.REFUSED_FLAGS + ("--session", "--namespace")
CHILD_START_TIMEOUT = 20
CHILD_STOP_WAIT = 2
CHILD_CALL_SLACK = 30
DEFAULT_CALL_TIMEOUT_MS = 120000
LINE_LIMIT = 256 * 1024 * 1024
EVENT_WAIT_LIMIT = 300
NO_SESSION = "No session yet: call connect first (new=true makes an agent profile of your own, without a prompt)."
INSTRUCTIONS = """\
Drives the Ardia browser the user is running. Call connect first: connect(name, new=true) makes an agent profile
of your own with no prompt; connect(name) on one of the owner's profiles waits until the owner allows it in Ardia.
The session lasts until disconnect, Ardia quits, control is turned off or 30 minutes without traffic.
The agent_browser_* tools are agent-browser's, driving that session's tabs: agent_browser_open, then
agent_browser_snapshot for @refs, then agent_browser_click, agent_browser_fill, ... with them.
run takes one of Ardia's own commands (see commands). tabs lists every profile, window, pin and tab, with the ids
run takes; it needs no session."""
TABS_DESCRIPTION = (
    "Everything open in Ardia, live: windows (id, kind, focused, the profile each shows) and every profile, the "
    "owner's and agents', with its pins (favorites and pinned tabs, once each, including those of profiles no "
    "window shows) and its tabs (id, window, title, url, folder, active). Private windows never appear. profile "
    "limits it to one profile. Pass a tab's id or window as run's tab or window."
)


def schema(properties: dict | None = None, required: tuple = ()) -> dict:
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


STRING = {"type": "string"}
ID = {"type": ["integer", "string"]}
TOOLS = [
    {
        "name": "connect",
        "description": "Connect to a profile; the session is kept by this server and never shown. new=true makes an agent profile named NAME with no prompt; otherwise NAME is an existing profile and the owner has to allow it in Ardia (up to 120 s).",
        "inputSchema": schema({"name": STRING, "new": {"type": "boolean", "default": False}, "agent": {**STRING, "description": "who is asking, shown to the owner (default: this MCP client's name)"}}, ("name",)),
    },
    {
        "name": "disconnect",
        "description": "End the session and close its connections.",
        "inputSchema": schema(),
    },
    {
        "name": "rename",
        "description": "Rename the session's agent profile (agent profiles only).",
        "inputSchema": schema({"name": STRING}, ("name",)),
    },
    {
        "name": "run",
        "description": "Run one of Ardia's commands (see commands) in the session's profile, as its menu item or shortcut would. tab targets one tab without focusing it.",
        "inputSchema": schema({"command": STRING, "arg": {**STRING, "description": "one of the command's variants"}, "window": ID, "tab": ID}, ("command",)),
    },
    {
        "name": "commands",
        "description": "List the commands run takes: ids, titles and variants.",
        "inputSchema": schema(),
    },
    {
        "name": "tabs",
        "description": TABS_DESCRIPTION,
        "inputSchema": schema({"profile": STRING}),
    },
    {
        "name": "wait_for_event",
        "description": "Wait for the next of Ardia's events (tab.opened, tab.navigated, window.focused, ...; none for any) and return it, or {timedOut: true}.",
        "inputSchema": schema({"events": {"type": "array", "items": STRING}, "timeout": {"type": "number", "default": 30, "maximum": EVENT_WAIT_LIMIT}, "full_urls": {"type": "boolean", "default": False}}),
    },
    {
        "name": "history",
        "description": "The owner's recent history per URL, newest first (owner profiles only, http(s) pages). domains=true rolls it up per domain.",
        "inputSchema": schema({"days": {"type": "number", "default": 1}, "limit": {"type": "integer", "default": 200}, "profile": STRING, "domains": {"type": "boolean", "default": False}}),
    },
]


class ToolError(Exception):
    def __init__(self, kind: str, message: str, code: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.code = code or kind


class ChildGone(Exception):
    pass


def forwarded_tools(profiles: str) -> list[dict]:
    listing = json.loads(FORWARDED_TOOLS.read_text(encoding="utf-8"))
    wanted = set()
    for profile in profiles.split(","):
        if profile not in listing["profiles"]:
            raise ValueError(f"no agent-browser tools profile {profile!r} (one of {', '.join(sorted(listing['profiles']))})")
        wanted.update(listing["profiles"][profile])
    tools = []
    for tool in listing["tools"]:
        if tool["name"] in wanted and tool["name"] not in DENIED_TOOLS:
            input_schema = dict(tool["inputSchema"])
            input_schema["properties"] = {k: v for k, v in input_schema.get("properties", {}).items() if k not in DROPPED_ARGUMENTS}
            if "required" in input_schema:
                input_schema["required"] = [k for k in input_schema["required"] if k not in DROPPED_ARGUMENTS]
            tools.append({**tool, "inputSchema": input_schema})
    return tools


def refused_extra_arg(arguments: dict) -> str | None:
    extra = arguments.get("extraArgs")
    if not isinstance(extra, list):
        return None
    for arg in extra:
        for flag in REFUSED_EXTRA_ARGS:
            if isinstance(arg, str) and (arg == flag or arg.startswith(flag + "=")):
                return flag
    return None


class AgentBrowser:
    def __init__(self, program: str, profiles: str, env: dict, on_notification):
        self.program = program
        self.profiles = profiles
        self.env = env
        self.on_notification = on_notification
        self.process = None
        self.pending: dict = {}
        self.next_id = 0
        self.tasks: list = []

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None and bool(self.tasks) and not self.tasks[0].done()

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            self.program, "mcp", "--tools", self.profiles, "--config", str(agent_browser.CONFIG),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=self.env, limit=LINE_LIMIT,
        )
        self.tasks = [asyncio.ensure_future(self.read()), asyncio.ensure_future(self.relay_stderr())]
        answer = await asyncio.wait_for(self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSIONS[0], "capabilities": {}, "clientInfo": {"name": "ardia", "version": __version__},
        }), CHILD_START_TIMEOUT)
        if "error" in answer:
            raise ChildGone(str(answer["error"].get("message") or answer["error"]))
        self.write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def write(self, message: dict) -> None:
        if self.process is None or self.process.stdin.is_closing():
            raise ChildGone("agent-browser has stopped")
        self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())

    async def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            self.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            if self.alive:
                try:
                    self.write({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": request_id}})
                except (ChildGone, OSError):
                    pass
            raise
        finally:
            self.pending.pop(request_id, None)

    async def read(self) -> None:
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "method" not in message:
                    future = self.pending.get(message.get("id"))
                    if future is not None and not future.done():
                        future.set_result(message)
                elif "id" in message:
                    answer = {"result": {}} if message["method"] == "ping" else {"error": {"code": -32601, "message": "not supported"}}
                    self.write({"jsonrpc": "2.0", "id": message["id"], **answer})
                else:
                    self.on_notification(message)
        except (ValueError, ConnectionError, ChildGone):
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ChildGone("agent-browser stopped mid-call"))

    async def relay_stderr(self) -> None:
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            sys.stderr.write(redact("agent-browser: " + line.decode("utf-8", "replace")))
            sys.stderr.flush()

    async def stop(self) -> None:
        process = self.process
        if process is not None and process.returncode is None:
            try:
                process.stdin.close()
                await asyncio.wait_for(process.wait(), CHILD_STOP_WAIT)
            except (asyncio.TimeoutError, OSError):
                for signal_name in ("terminate", "kill"):
                    try:
                        getattr(process, signal_name)()
                        await asyncio.wait_for(process.wait(), CHILD_STOP_WAIT)
                        break
                    except ProcessLookupError:
                        break
                    except asyncio.TimeoutError:
                        continue
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.to_thread(agent_browser.stop_daemon, self.env)


class Server:
    def __init__(self, ardia: Ardia, out, profiles: str = "core"):
        self.ardia = ardia
        self.out = out
        self.client = None
        self.owned = None
        self.running: dict = {}
        self.write_lock = threading.Lock()
        self.profiles = profiles
        self.forwarded = forwarded_tools(profiles)
        self.tools = TOOLS + self.forwarded
        self.child: AgentBrowser | None = None
        self.child_lock = asyncio.Lock()

    def send(self, message: dict) -> None:
        line = redact(json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str))
        with self.write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def reply(self, request_id, result=None, error=None) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, **({"error": error} if error else {"result": result})})

    async def serve(self, reader) -> None:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        for signum in (signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(signum, current.cancel)
        lines: asyncio.Queue = asyncio.Queue()

        def read_lines() -> None:
            for line in iter(reader.readline, ""):
                loop.call_soon_threadsafe(lines.put_nowait, line)
            loop.call_soon_threadsafe(lines.put_nowait, "")

        threading.Thread(target=read_lines, daemon=True).start()
        try:
            while True:
                line = await lines.get()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    self.reply(None, error={"code": -32700, "message": "parse error"})
                    continue
                if isinstance(message, dict):
                    self.handle(message)
        finally:
            for task in list(self.running.values()):
                task.cancel()
            await asyncio.gather(*self.running.values(), return_exceptions=True)
            await self.stop_child()
            await self.end_owned_session()

    async def stop_child(self) -> None:
        child, self.child = self.child, None
        if child is not None:
            await child.stop()

    def child_notification(self, message: dict) -> None:
        if message.get("method") == "notifications/progress":
            self.send(message)

    async def started_child(self) -> AgentBrowser:
        async with self.child_lock:
            if self.child is not None and self.child.alive:
                return self.child
            await self.stop_child()
            session = self.ardia.session
            add_secret(session)
            try:
                program = agent_browser.binary()
                found = endpoint.from_control_file(endpoint.control_path(self.ardia.root), session)
            except agent_browser.Missing as error:
                raise ToolError("error", str(error), "agent_browser_missing") from None
            except endpoint.EndpointError as error:
                raise ToolError("unreachable", str(error)) from None
            child = AgentBrowser(program, self.profiles, agent_browser.environment(found.ws, session), self.child_notification)
            try:
                await child.start()
            except (OSError, ChildGone, asyncio.TimeoutError) as error:
                await child.stop()
                raise ToolError("error", f"agent-browser didn't start ({type(error).__name__}: {error})", "agent_browser") from None
            self.child = child
            return child

    async def session_ended(self) -> bool:
        try:
            found = endpoint.from_control_file(endpoint.control_path(self.ardia.root), self.ardia.session)
        except endpoint.EndpointError:
            return True
        return await asyncio.to_thread(endpoint.session_gone, found)

    async def forward(self, request_id, spec: dict, arguments: dict, meta: dict) -> None:
        unknown = sorted(set(arguments) - set(spec["inputSchema"].get("properties", {})))
        if unknown:
            self.reply(request_id, error={"code": -32602, "message": f"{spec['name']}: unknown argument {unknown[0]}"})
            return
        try:
            self.require_session()
            flag = refused_extra_arg(arguments)
            if flag:
                raise ToolError("refused", f"extraArgs can't carry {flag}: the agent-browser tools always drive this session", "refused_argument")
            child = await self.started_child()
            timeout = arguments.get("timeoutMs") if isinstance(arguments.get("timeoutMs"), int) else DEFAULT_CALL_TIMEOUT_MS
            params = {"name": spec["name"], "arguments": arguments, **({"_meta": meta} if meta else {})}
            try:
                answer = await child.request("tools/call", params, timeout / 1000 + CHILD_CALL_SLACK)
            except (ChildGone, asyncio.TimeoutError) as error:
                if await self.session_ended():
                    await self.stop_child()
                    raise ToolError("session", endpoint.SESSION_ENDED) from None
                if isinstance(error, asyncio.TimeoutError):
                    await self.stop_child()
                    raise ToolError("error", f"agent-browser didn't answer {spec['name']}; it has been stopped and the next call starts it again", "agent_browser") from None
                raise ToolError("error", f"{error}; the next call starts it again", "agent_browser") from None
        except asyncio.CancelledError:
            return
        except ToolError as error:
            self.reply(request_id, failure(error.kind, error.code, error.message))
            return
        if "error" in answer:
            self.reply(request_id, error=answer["error"])
            return
        result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
        if result.get("isError") and await self.session_ended():
            await self.stop_child()
            self.reply(request_id, failure("session", "session", endpoint.SESSION_ENDED))
            return
        self.reply(request_id, result)

    async def end_owned_session(self) -> None:
        owned, self.owned = self.owned, None
        if owned is None:
            return
        try:
            await asyncio.to_thread(Ardia(self.ardia.root, owned).disconnect)
        except ArdiaError:
            pass

    def handle(self, message: dict) -> None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "notifications/cancelled":
            task = self.running.get(params.get("requestId"))
            if task is not None:
                task.cancel()
            return
        if request_id is None:
            return
        if method == "initialize":
            self.client = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else None
            asked = params.get("protocolVersion")
            self.reply(request_id, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ardia", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            self.reply(request_id, {})
        elif method == "tools/list":
            self.reply(request_id, {"tools": self.tools})
        elif method == "tools/call":
            task = asyncio.ensure_future(self.call(request_id, params))
            self.running[request_id] = task
            task.add_done_callback(lambda _t: self.running.pop(request_id, None))
        else:
            self.reply(request_id, error={"code": -32601, "message": f"no method {method}"})

    async def call(self, request_id, params: dict) -> None:
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        spec = next((t for t in self.tools if t["name"] == name), None)
        if spec is None:
            self.reply(request_id, error={"code": -32602, "message": f"no tool {name}"})
            return
        if spec in self.forwarded:
            await self.forward(request_id, spec, arguments, meta)
            return
        problem = argument_problem(spec["inputSchema"], arguments)
        if problem:
            self.reply(request_id, error={"code": -32602, "message": f"{name}: {problem}"})
            return
        try:
            data = await getattr(self, f"tool_{name}")(meta.get("progressToken"), **arguments)
        except asyncio.CancelledError:
            return
        except ToolError as error:
            self.reply(request_id, failure(error.kind, error.code, error.message))
            return
        except ArdiaError as error:
            message = NO_SESSION if isinstance(error, SessionGone) and self.ardia.session is None else error.message
            self.reply(request_id, failure(error.kind, error.code, message))
            return
        except Exception as error:
            self.reply(request_id, failure("error", "error", f"{type(error).__name__}: {error}"))
            return
        self.reply(request_id, success(data))

    def progress(self, token, message: str) -> None:
        if token is not None:
            self.send({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": token, "progress": 0, "message": message}})

    def require_session(self) -> None:
        if self.ardia.session is None:
            raise ToolError("session", NO_SESSION)

    async def tool_connect(self, token, name: str, new: bool = False, agent: str | None = None):
        cancelled = threading.Event()

        def sleep(seconds: float) -> None:
            if cancelled.wait(seconds):
                raise Expired("cancelled")

        def waiting() -> None:
            self.progress(token, "Waiting for the owner to allow it in Ardia")

        who = agent or os.environ.get("ARDIA_AGENT") or (self.client or {}).get("name")
        work = asyncio.ensure_future(asyncio.to_thread(self.ardia.connect, name, new, who, waiting, sleep))
        try:
            answer = await asyncio.shield(work)
        except asyncio.CancelledError:
            cancelled.set()
            await asyncio.gather(work, return_exceptions=True)
            raise
        if self.child is not None and self.child.env.get("AGENT_BROWSER_SESSION") != agent_browser.session_name(answer["session"]):
            await self.stop_child()
        if self.owned != answer["session"]:
            await self.end_owned_session()
        self.owned = answer["session"]
        return {"profile": answer["profile"], "kind": answer["kind"]}

    async def tool_disconnect(self, _token):
        self.require_session()
        await self.stop_child()
        await asyncio.to_thread(self.ardia.disconnect)
        self.ardia.session = self.owned = None
        return {"disconnected": True}

    async def tool_rename(self, _token, name: str):
        self.require_session()
        await asyncio.to_thread(self.ardia.rename, name)
        return {"renamed": name}

    async def tool_run(self, _token, command: str, arg: str | None = None, window=None, tab=None):
        self.require_session()
        return {"result": await asyncio.to_thread(self.ardia.run, command, arg, window, tab)}

    async def tool_commands(self, _token):
        return {"commands": await self.ardia.commands()}

    async def tool_tabs(self, _token, profile: str | None = None):
        return await self.ardia.tabs(profile)

    async def tool_wait_for_event(self, _token, events: list | None = None, timeout: float = 30, full_urls: bool = False):
        from ardia_cli.control import check_events

        try:
            check_events(events or [])
        except ValueError as error:
            raise ToolError("refused", str(error), "unknown_event") from None
        stream = self.ardia.events(*(events or []), full_urls=full_urls)
        try:
            return await asyncio.wait_for(stream.__anext__(), max(0, min(float(timeout), EVENT_WAIT_LIMIT)))
        except asyncio.TimeoutError:
            return {"timedOut": True}
        finally:
            await stream.aclose()

    async def tool_history(self, _token, days: float = 1, limit: int = 200, profile: str | None = None, domains: bool = False):
        return {"history": await self.ardia.history(days, limit, profile, domains)}



JSON_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float), "array": list, "object": dict}


def argument_problem(input_schema: dict, arguments: dict) -> str | None:
    properties = input_schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return f"unknown argument {unknown[0]}"
    missing = [name for name in input_schema["required"] if name not in arguments]
    if missing:
        return f"missing argument {missing[0]}"
    for name, value in arguments.items():
        allowed = properties[name].get("type")
        kinds = allowed if isinstance(allowed, list) else [allowed]
        if value is None and name not in input_schema["required"]:
            continue
        if not any(isinstance(value, JSON_TYPES[k]) and not (isinstance(value, bool) and k in ("integer", "number")) for k in kinds if k):
            return f"{name} must be {' or '.join(kinds)}"
        if isinstance(value, list) and not all(isinstance(item, str) for item in value):
            return f"{name} must be a list of strings"
    return None


def success(data) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]}


def failure(kind: str, code: str, message: str) -> dict:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": kind, "code": code, "message": message},
        "isError": True,
    }


def main(data_dir: str | None = None, session: str | None = None, tools: str = "core") -> int:
    from ardia_cli.endpoint import SESSION_EXIT, SessionError, session_id

    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        token = session_id(session)
    except SessionError as error:
        sys.stderr.write(f"ardia mcp: {error}\n")
        return SESSION_EXIT
    try:
        server = Server(Ardia.at(data_dir, token), out, tools)
    except ValueError as error:
        sys.stderr.write(f"ardia mcp: {error}\n")
        return 64
    try:
        asyncio.run(server.serve(sys.stdin))
    except KeyboardInterrupt:
        return 130
    except asyncio.CancelledError:
        return 143
    return 0
