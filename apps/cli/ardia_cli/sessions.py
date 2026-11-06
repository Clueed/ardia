import json
import os
import signal
import sys
import time
from contextlib import contextmanager

from ardia_cli.endpoint import (
    SESSION_EXIT,
    UNREACHABLE_EXIT,
    EndpointError,
    RouteError,
    SessionError,
    control_call,
    data_root,
    require_control,
    require_session,
    session_call,
)
from ardia_cli.redact import add_secret

DEFAULT_AGENT = "agent"
POLL_INTERVAL = 0.25
CONNECT_WAIT = 120
CANCEL_TIMEOUT = 2
DENIED_EXIT = 4
EXPIRED_EXIT = 5
INTERRUPTED_EXIT = 130
WAITING = "Waiting for you to allow it in Ardia…"
MESSAGES = {
    "no-such-profile": "no profile is named {name!r} (see ardia profiles)",
    "name-taken": "a profile is already named {existing!r}: pick another name, or ardia connect {existing!r} to use it",
    "bad-name": "{name!r} isn't a usable profile name (1 to 60 characters, no control characters)",
    "not-agent": "this session is on one of the owner's profiles; only agent profiles can be renamed",
}


class Stopped(Exception):
    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


@contextmanager
def stopped_by_signals():
    def stop(signum, _frame):
        raise Stopped(signum)

    previous = {}
    try:
        for signum in STOP_SIGNALS:
            previous[signum] = signal.signal(signum, stop)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def complain(command: str, text: str) -> None:
    sys.stdout.flush()
    sys.stderr.write(f"ardia {command}: {text}\n")
    sys.stderr.flush()


def route_message(code: str, name: str | None, control=None) -> str:
    template = MESSAGES.get(code)
    if not template:
        return f"Ardia refused it ({code})"
    if code == "name-taken" and control is not None and name:
        return template.format(name=name, existing=existing_name(control, name))
    return template.format(name=name or "", existing=name or "")


def existing_name(control, name: str) -> str:
    folded = name.strip().lower()
    try:
        rows = control_call(control, "profiles").get("profiles") or []
    except (EndpointError, RouteError):
        return name
    return next((str(p["name"]) for p in rows if isinstance(p, dict) and str(p.get("name", "")).strip().lower() == folded), name)


def profiles(args) -> int:
    try:
        control = require_control(data_root(args.data_dir))
        answer = control_call(control, "profiles")
    except EndpointError as error:
        complain("profiles", str(error))
        return UNREACHABLE_EXIT
    except RouteError as error:
        complain("profiles", route_message(error.code, None))
        return 1
    rows = [
        {"name": str(p.get("name", "")), "kind": "agent" if p.get("kind") == "agent" else "real", "connected": int(p.get("connected") or 0)}
        for p in answer.get("profiles") or []
        if isinstance(p, dict)
    ]
    if args.json:
        sys.stdout.write(json.dumps({"profiles": rows}, indent=2, ensure_ascii=False) + "\n")
        return 0
    if not rows:
        sys.stdout.write("no profiles\n")
    for row in rows:
        connected = f", {row['connected']} connected" if row["connected"] else ""
        sys.stdout.write(f"{row['name']} ({row['kind']}{connected})\n")
    return 0


def connect(args, raw_stdout) -> int:
    name = args.new if args.new is not None else args.name
    if name is None or (args.new is not None and args.name is not None):
        complain("connect", "give a profile NAME, or --new NAME for a profile of your own")
        return 1
    agent = (args.agent or os.environ.get("ARDIA_AGENT") or "").strip() or DEFAULT_AGENT
    target = {"new": name} if args.new is not None else {"profile": name}
    request = None
    control = None
    try:
        with stopped_by_signals():
            control = require_control(data_root(args.data_dir))
            request = control_call(control, "connect", agent=agent, **target).get("request")
            if not isinstance(request, str) or not request:
                raise EndpointError("Ardia gave no request id")
            if args.new is None:
                sys.stderr.write(WAITING + "\n")
                sys.stderr.flush()
            state = wait_for_answer(control, request)
    except (KeyboardInterrupt, Stopped) as stop:
        if request:
            cancel(control, request)
        complain("connect", "cancelled")
        return 128 + stop.signum if isinstance(stop, Stopped) else INTERRUPTED_EXIT
    except EndpointError as error:
        complain("connect", str(error))
        return UNREACHABLE_EXIT
    except RouteError as error:
        complain("connect", route_message(error.code, name, control))
        return 1
    if state is None:
        cancel(control, request)
        state = {"state": "expired"}
    if state.get("state") == "denied":
        complain("connect", f"the owner denied {agent!r} the use of {name!r}")
        return DENIED_EXIT
    if state.get("state") != "allowed":
        complain("connect", f"no answer within {CONNECT_WAIT} s, so the request expired")
        return EXPIRED_EXIT
    session = state.get("session")
    if not isinstance(session, str) or not session:
        complain("connect", "Ardia allowed it but sent no session")
        return UNREACHABLE_EXIT
    add_secret(session)
    if args.json:
        output = json.dumps({"session": session, "profile": state.get("profile") or name, "kind": state.get("kind") or ("agent" if args.new is not None else "real")}, ensure_ascii=False)
    else:
        output = session
    sys.stderr.flush()
    raw_stdout.write(output + "\n")
    raw_stdout.flush()
    return 0


def wait_for_answer(control, request: str) -> dict | None:
    deadline = time.monotonic() + CONNECT_WAIT
    while True:
        try:
            state = control_call(control, "connect", request=request)
        except RouteError:
            return {"state": "expired"}
        if state.get("state") != "pending":
            return state
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(POLL_INTERVAL, remaining))


def cancel(control, request: str) -> None:
    from ardia_cli.endpoint import get_json

    try:
        get_json(control.url("connect", token=control.token, request=request, cancel=1), timeout=CANCEL_TIMEOUT)
    except (Exception, KeyboardInterrupt):
        pass


def disconnect(args) -> int:
    return session_command(args, "disconnect", "disconnected")


def rename(args) -> int:
    return session_command(args, "rename", f"renamed to {args.name}", name=args.name)


def session_command(args, route: str, done: str, **params) -> int:
    control = None
    try:
        session = require_session(args.session)
        control = require_control(data_root(args.data_dir))
        session_call(control, session, route, **params)
    except SessionError as error:
        complain(route, str(error))
        return SESSION_EXIT
    except EndpointError as error:
        complain(route, str(error))
        return UNREACHABLE_EXIT
    except RouteError as error:
        complain(route, route_message(error.code, params.get("name"), control))
        return 1
    sys.stdout.write(done + "\n")
    return 0
