import json
import signal
import sys
from contextlib import contextmanager

from ardia_cli.api import Ardia, ArdiaError, Denied, Expired, Refused, SessionGone

UNREACHABLE_EXIT = 2
SESSION_EXIT = 6
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


def route_message(code: str, name: str | None, ardia: Ardia | None = None) -> str:
    template = MESSAGES.get(code)
    if not template:
        return f"Ardia refused it ({code})"
    if code == "name-taken" and ardia is not None and name:
        return template.format(name=name, existing=existing_name(ardia, name))
    return template.format(name=name or "", existing=name or "")


def existing_name(ardia: Ardia, name: str) -> str:
    folded = name.strip().lower()
    try:
        rows = ardia.profiles()
    except ArdiaError:
        return name
    return next((row["name"] for row in rows if row["name"].strip().lower() == folded), name)


def failed(command: str, error: ArdiaError, name: str | None = None, ardia: Ardia | None = None) -> int:
    if isinstance(error, Refused):
        complain(command, route_message(error.code, name, ardia))
        return 1
    complain(command, error.message)
    if isinstance(error, SessionGone):
        return SESSION_EXIT
    if isinstance(error, Denied):
        return DENIED_EXIT
    if isinstance(error, Expired):
        return EXPIRED_EXIT
    return UNREACHABLE_EXIT


def profiles(args) -> int:
    try:
        rows = Ardia.at(args.data_dir).profiles()
    except ArdiaError as error:
        return failed("profiles", error)
    if args.json:
        sys.stdout.write(json.dumps({"profiles": rows}, indent=2, ensure_ascii=False) + "\n")
        return 0
    if not rows:
        sys.stdout.write("no profiles\n")
    for row in rows:
        connected = f", {row['connected']} connected" if row["connected"] else ""
        sys.stdout.write(f"{row['name']} ({row['kind']}{connected})\n")
    return 0


def waiting() -> None:
    sys.stderr.write(WAITING + "\n")
    sys.stderr.flush()


def connect(args, raw_stdout) -> int:
    name = args.new if args.new is not None else args.name
    if name is None or (args.new is not None and args.name is not None):
        complain("connect", "give a profile NAME, or --new NAME for a profile of your own")
        return 1
    ardia = Ardia.at(args.data_dir)
    try:
        with stopped_by_signals():
            answer = ardia.connect(name, new=args.new is not None, agent=args.agent, on_waiting=waiting)
    except (KeyboardInterrupt, Stopped) as stop:
        complain("connect", "cancelled")
        return 128 + stop.signum if isinstance(stop, Stopped) else INTERRUPTED_EXIT
    except ArdiaError as error:
        return failed("connect", error, name, ardia)
    output = json.dumps(answer, ensure_ascii=False) if args.json else answer["session"]
    sys.stderr.flush()
    raw_stdout.write(output + "\n")
    raw_stdout.flush()
    return 0


def disconnect(args) -> int:
    return session_command(args, "disconnect", "disconnected")


def rename(args) -> int:
    return session_command(args, "rename", f"renamed to {args.name}", args.name)


def session_command(args, route: str, done: str, name: str | None = None) -> int:
    ardia = Ardia.at(args.data_dir, args.session)
    try:
        ardia.rename(name) if route == "rename" else ardia.disconnect()
    except ArdiaError as error:
        return failed(route, error, name, ardia)
    sys.stdout.write(done + "\n")
    return 0
