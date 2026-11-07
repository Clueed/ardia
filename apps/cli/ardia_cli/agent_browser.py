import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from ardia_cli import endpoint

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "agent-browser.json"
BUNDLED = HERE / "bin" / "agent-browser"
REFUSED_FLAGS = ("--cdp", "--auto-connect", "--config")
DROPPED_ENV = ("AGENT_BROWSER_CDP", "AGENT_BROWSER_AUTO_CONNECT", "AGENT_BROWSER_PROVIDER", "AGENT_BROWSER_CDP_HEADERS", "AGENT_BROWSER_NAMESPACE", "AGENT_BROWSER_CONFIG")
SESSION_FREE = {"--version", "-V", "--help", "-h", "help", "skills"}
NO_SESSION = endpoint.NO_SESSION.replace("pass --session ID", "pass --ardia-session ID")
DAEMON_STOP_WAIT = 2


class Missing(Exception):
    pass


def binary() -> str:
    chosen = os.environ.get("ARDIA_AGENT_BROWSER")
    if chosen:
        if not os.access(chosen, os.X_OK):
            raise Missing(f"$ARDIA_AGENT_BROWSER ({chosen}) isn't an executable")
        return chosen
    if os.access(BUNDLED, os.X_OK):
        return str(BUNDLED)
    raise Missing("agent-browser isn't bundled with this ardia: set $ARDIA_AGENT_BROWSER to an agent-browser binary")


def session_name(session: str) -> str:
    return hashlib.sha256(session.encode()).hexdigest()[:16]


def environment(ws: str | None, session: str | None, base: dict | None = None) -> dict:
    env = {key: value for key, value in (os.environ if base is None else base).items() if key not in DROPPED_ENV}
    env.update(AGENT_BROWSER_NO_VERSION_CHECK="1", AGENT_BROWSER_CONFIG=str(CONFIG))
    if ws and session:
        env.update(AGENT_BROWSER_CDP=ws, AGENT_BROWSER_SESSION=session_name(session))
    return env


def refused_flag(args) -> str | None:
    for arg in args:
        if not isinstance(arg, str):
            continue
        for flag in REFUSED_FLAGS:
            if arg == flag or arg.startswith(flag + "="):
                return flag
    return None


def refusal(args: list[str]) -> str | None:
    flag = refused_flag(args)
    if flag:
        return f"{flag} isn't allowed; ardia browse always drives the connected Ardia session"
    if any("cdp-url" in arg.split() for arg in args):
        return "get cdp-url isn't allowed: the session's address carries its token"
    return None


def daemon_dir(env: dict) -> Path:
    if env.get("AGENT_BROWSER_SOCKET_DIR"):
        return Path(env["AGENT_BROWSER_SOCKET_DIR"])
    if env.get("XDG_RUNTIME_DIR"):
        return Path(env["XDG_RUNTIME_DIR"]) / "agent-browser"
    return Path(env.get("HOME") or Path.home()) / ".agent-browser"


def stop_daemon(env: dict) -> None:
    name = env.get("AGENT_BROWSER_SESSION")
    if not name:
        return
    try:
        pid = int((daemon_dir(env) / f"{name}.pid").read_text().strip())
        command = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return
    if pid <= 1 or not command.endswith("agent-browser"):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + DAEMON_STOP_WAIT
        while time.monotonic() < deadline:
            time.sleep(0.05)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def take_ardia_flags(argv: list[str]) -> tuple[dict, list[str]]:
    found: dict = {}
    rest: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "--":
            rest.extend(argv[index - 1:])
            break
        flag, eq, value = arg.partition("=")
        if flag in ("--ardia-session", "--data-dir"):
            if not eq:
                if index >= len(argv):
                    raise SystemExit(f"ardia browse: {flag} needs a value")
                value = argv[index]
                index += 1
            found[flag[2:].replace("-", "_")] = value
        else:
            rest.append(arg)
    return found, rest


def main(argv: list[str]) -> int:
    found, args = take_ardia_flags(argv)
    refused = refusal(args)
    if refused:
        sys.stderr.write(f"ardia browse: {refused}\n")
        return 64
    first = next((arg for arg in args if not arg.startswith("-") or arg in SESSION_FREE), None)
    try:
        session = endpoint.session_id(found.get("ardia_session"))
        if session is None and not (first in SESSION_FREE or not args):
            raise endpoint.SessionError(NO_SESSION)
        program = binary()
        if session is None:
            os.execve(program, [program, *args], environment(None, None))
        found_endpoint = endpoint.from_control_file(endpoint.control_path(endpoint.data_root(found.get("data_dir"))), session)
        if endpoint.session_gone(found_endpoint):
            raise endpoint.SessionError(endpoint.SESSION_ENDED)
    except Missing as error:
        sys.stderr.write(f"ardia browse: {error}\n")
        return 1
    except endpoint.SessionError as error:
        sys.stderr.write(f"ardia browse: {error}\n")
        return endpoint.SESSION_EXIT
    except endpoint.EndpointError as error:
        sys.stderr.write(f"ardia browse: {error}\n")
        return endpoint.UNREACHABLE_EXIT
    os.execve(program, [program, *args], environment(found_endpoint.ws, session))
    return 1
