import json
import os
import sys
import time

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
    "name-taken": "a profile is already named {name!r}: pick another name, or ardia connect {name!r} to use it",
    "bad-name": "{name!r} isn't a usable profile name (1 to 60 characters, no control characters)",
    "not-agent": "this session is on one of the owner's profiles; only agent profiles can be renamed",
}


def complain(command: str, text: str) -> None:
    sys.stdout.flush()
    sys.stderr.write(f"ardia {command}: {text}\n")
    sys.stderr.flush()


def route_message(code: str, name: str | None) -> str:
    template = MESSAGES.get(code)
    return template.format(name=name or "") if template else f"Ardia refused it ({code})"


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
    try:
        control = require_control(data_root(args.data_dir))
        request = control_call(control, "connect", agent=agent, **target).get("request")
        if not isinstance(request, str) or not request:
            raise EndpointError("Ardia gave no request id")
        if args.new is None:
            sys.stderr.write(WAITING + "\n")
            sys.stderr.flush()
        state = wait_for_answer(control, request)
    except KeyboardInterrupt:
        if request:
            cancel(control, request)
        complain("connect", "cancelled")
        return INTERRUPTED_EXIT
    except EndpointError as error:
        complain("connect", str(error))
        return UNREACHABLE_EXIT
    except RouteError as error:
        complain("connect", route_message(error.code, name))
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
        complain(route, route_message(error.code, params.get("name")))
        return 1
    sys.stdout.write(done + "\n")
    return 0
