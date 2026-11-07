import asyncio
import json
import os
import sys
import threading

from ardia_cli import __version__
from ardia_cli.api import Ardia, ArdiaError, Expired, SessionGone, Unreachable
from ardia_cli.redact import redact

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
BROWSE_TIMEOUT = 180
EVENT_WAIT_LIMIT = 300
NO_SESSION = "No session yet: call connect first (new=true makes an agent profile of your own, without a prompt)."
INSTRUCTIONS = """\
Drives the Ardia browser the user is running. Call connect first: connect(name, new=true) makes an agent profile
of your own with no prompt; connect(name) on one of the owner's profiles waits until the owner allows it in Ardia.
The session lasts until disconnect, Ardia quits, control is turned off or 30 minutes without traffic.
browse takes agent-browser's command line (snapshot, click @e1, fill @e2 "text", open URL, ...) in that profile;
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
        "name": "browse",
        "description": "Run one agent-browser command against the session's profile, e.g. [\"snapshot\", \"-i\"], [\"click\", \"@e3\"], [\"fill\", \"@e2\", \"hello\"], [\"open\", \"https://example.com\"]. Returns its JSON data.",
        "inputSchema": schema({"args": {"type": "array", "items": STRING, "minItems": 1}}, ("args",)),
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


class Server:
    def __init__(self, ardia: Ardia, out):
        self.ardia = ardia
        self.out = out
        self.client = None
        self.owned = None
        self.running: dict = {}
        self.write_lock = threading.Lock()

    def send(self, message: dict) -> None:
        line = redact(json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str))
        with self.write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def reply(self, request_id, result=None, error=None) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, **({"error": error} if error else {"result": result})})

    async def serve(self, reader) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, reader.readline)
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                self.reply(None, error={"code": -32700, "message": "parse error"})
                continue
            if isinstance(message, dict):
                self.handle(message)
        for task in list(self.running.values()):
            task.cancel()
        await asyncio.gather(*self.running.values(), return_exceptions=True)
        await self.end_owned_session()

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
            self.reply(request_id, {"tools": TOOLS})
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
        spec = next((t for t in TOOLS if t["name"] == name), None)
        if spec is None:
            self.reply(request_id, error={"code": -32602, "message": f"no tool {name}"})
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
        if self.owned != answer["session"]:
            await self.end_owned_session()
        self.owned = answer["session"]
        return {"profile": answer["profile"], "kind": answer["kind"]}

    async def tool_disconnect(self, _token):
        self.require_session()
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

    async def tool_browse(self, _token, args: list):
        self.require_session()
        if not args:
            raise ToolError("refused", "give a command, like [\"snapshot\"]", "bad_request")
        env = dict(os.environ, ARDIA_SESSION=self.ardia.session)
        if self.ardia.root is not None:
            env["ARDIA_DATA_DIR"] = str(self.ardia.root)
        package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = f"import sys; sys.path.insert(0, {package_parent!r}); from ardia_cli.cli import main; sys.exit(main(sys.argv[1:]))"
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", code, "browse", "--json", *args,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), BROWSE_TIMEOUT)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            process.terminate()
            await process.wait()
            raise
        return browse_answer(process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))

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


def browse_answer(status: int, out: str, err: str):
    try:
        answer = json.loads(out)
    except ValueError:
        answer = None
    if isinstance(answer, list):
        return {"batch": answer}
    if isinstance(answer, dict) and "success" in answer:
        if answer.get("success"):
            return answer.get("data")
        message = str(answer.get("error") or err.strip() or f"ardia browse exited {status}")
        if status == 6:
            raise SessionGone(message)
        raise ToolError("unreachable" if status == 2 else "browse", message, answer.get("code"))
    detail = (err.strip() or out.strip() or f"ardia browse exited {status}").splitlines()[-1]
    if status == 6:
        raise SessionGone(detail)
    if status == 2:
        raise Unreachable(detail)
    raise ToolError("browse", detail)


def success(data) -> dict:
    structured = data if isinstance(data, dict) else {"result": data}
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}], "structuredContent": structured}


def failure(kind: str, code: str, message: str) -> dict:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": kind, "code": code, "message": message},
        "isError": True,
    }


def main(data_dir: str | None = None, session: str | None = None) -> int:
    from ardia_cli.endpoint import SESSION_EXIT, SessionError, session_id

    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        token = session_id(session)
    except SessionError as error:
        sys.stderr.write(f"ardia mcp: {error}\n")
        return SESSION_EXIT
    server = Server(Ardia.at(data_dir, token), out)
    try:
        asyncio.run(server.serve(sys.stdin))
    except KeyboardInterrupt:
        return 130
    return 0
