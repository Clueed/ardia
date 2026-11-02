import errno
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from ardia_cli.redact import add_secret

NOT_REACHABLE = (
    "Ardia isn't running, or \"Let the ardia command control Ardia\" is off in Settings."
)
NO_SESSION = (
    "Connect first: run `ardia connect --new NAME` (a profile of your own) or `ardia connect NAME` (an existing one), "
    "then pass --session ID or set $ARDIA_SESSION."
)
SESSION_ENDED = (
    "That session has ended (ardia disconnect, Ardia quit, control turned off, or 30 minutes idle) or never existed: "
    "run `ardia connect` again."
)
ROUTE_TIMEOUT = 5
UNREACHABLE_EXIT = 2
SESSION_EXIT = 6
CONTROL_FILE = "ArdiaGateway.json"
INSTALLED_DATA_DIR = Path.home() / "Library" / "Application Support" / "com.ardia.browser"
_BROWSER_PATH = re.compile(r"^/devtools/browser/[0-9A-Za-z-]{1,128}$")
_TOKEN = re.compile(r"^[\x21-\x7e]{16,1024}$")
_MAX_CONTROL_FILE = 64 * 1024


class EndpointError(Exception):
    pass


class SessionError(EndpointError):
    pass


class RouteError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Endpoint:
    ws: str
    source: str
    explicit: bool
    active: str | None = None


@dataclass(frozen=True)
class Control:
    port: int
    browser: str
    token: str

    def url(self, route: str, **params) -> str:
        return f"http://127.0.0.1:{self.port}/ardia/{route}?{query(**params)}"


def query(**params) -> str:
    return "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params.items())


def resolve(ws: str | None = None, port: int | None = None, data_dir: str | None = None, session: str | None = None) -> Endpoint:
    if ws:
        return _from_ws(ws, "--ws")
    if port is not None:
        return _from_port(port)
    env_ws = os.environ.get("ARDIA_CDP_URL")
    if env_ws:
        return _from_ws(env_ws, "ARDIA_CDP_URL")
    return from_control_file(control_path(data_root(data_dir)), session_id(session))


def session_id(session: str | None = None) -> str | None:
    value = session if session is not None else os.environ.get("ARDIA_SESSION")
    value = (value or "").strip()
    if not value:
        return None
    add_secret(value)
    if not _TOKEN.match(value):
        raise SessionError(SESSION_ENDED)
    return value


def require_session(session: str | None) -> str:
    value = session_id(session)
    if value is None:
        raise SessionError(NO_SESSION)
    return value


def data_root(data_dir: str | None = None) -> Path:
    root = data_dir or os.environ.get("ARDIA_DATA_DIR")
    return Path(root).expanduser() if root else INSTALLED_DATA_DIR


def explicit_data_root(data_dir: str | None = None) -> Path | None:
    root = data_dir or os.environ.get("ARDIA_DATA_DIR")
    return Path(root).expanduser() if root else None


def control_path(root: Path) -> Path:
    return root / CONTROL_FILE


def require_control(root: Path) -> Control:
    return read_control(control_path(root))


def _from_ws(url: str, source: str) -> Endpoint:
    parts = urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.netloc or not parts.path.startswith("/devtools/browser/"):
        raise EndpointError(f"{source} must be a ws://host:port/devtools/browser/<id> URL")
    for token in parse_qs(parts.query).get("token", []):
        add_secret(token)
    return Endpoint(url, source, True)


def _from_port(port: int) -> Endpoint:
    import urllib.request

    if not 0 < port < 65536:
        raise EndpointError(f"--port must be between 1 and 65535, not {port}")
    try:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct.open(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
            info = json.loads(response.read(_MAX_CONTROL_FILE))
    except Exception as error:
        raise EndpointError(f"no DevTools server answers on 127.0.0.1:{port} ({_reason(error)})") from None
    ws = info.get("webSocketDebuggerUrl") if isinstance(info, dict) else None
    if not isinstance(ws, str):
        raise EndpointError(f"127.0.0.1:{port}/json/version has no webSocketDebuggerUrl")
    return _from_ws(ws, f"--port {port}")


def _reason(error: Exception) -> str:
    reason = getattr(error, "reason", None)
    return str(reason or error) or type(error).__name__


def from_control_file(path: Path, session: str | None) -> Endpoint:
    control = read_control(path)
    if session is None:
        raise SessionError(NO_SESSION)
    return Endpoint(f"ws://127.0.0.1:{control.port}{control.browser}?{query(token=session)}", str(path), False, control.url("active", token=session))


def read_control(path: Path) -> Control:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise EndpointError(NOT_REACHABLE) from None
    except OSError as error:
        reason = "is a symbolic link" if error.errno == errno.ELOOP else error.strerror
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} {reason})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EndpointError(f"{NOT_REACHABLE} ({path.name} isn't a regular file)")
        if info.st_uid != os.getuid():
            raise EndpointError(f"{NOT_REACHABLE} ({path.name} belongs to another user)")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise EndpointError(f"{NOT_REACHABLE} ({path.name} must be mode 0600)")
        raw = os.read(fd, _MAX_CONTROL_FILE + 1)
    finally:
        os.close(fd)
    try:
        control = json.loads(raw)
    except ValueError:
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} isn't valid JSON)") from None
    if not isinstance(control, dict):
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} isn't valid)")
    port = control.get("port")
    browser = control.get("browser")
    token = control.get("token")
    pid = control.get("pid")
    if not (isinstance(port, int) and 0 < port < 65536):
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} has no valid port)")
    if not (isinstance(browser, str) and _BROWSER_PATH.match(browser)):
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} has no valid browser path)")
    if not (isinstance(token, str) and _TOKEN.match(token)):
        raise EndpointError(f"{NOT_REACHABLE} ({path.name} has no valid token)")
    add_secret(token)
    if not (isinstance(pid, int) and pid > 1 and _alive(pid)):
        raise EndpointError(NOT_REACHABLE)
    return Control(port, browser, token)


def get_json(url: str, timeout: float = ROUTE_TIMEOUT):
    import urllib.error
    import urllib.request

    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with direct.open(url, timeout=timeout) as response:
            raw = response.read(_MAX_CONTROL_FILE)
    except urllib.error.HTTPError as error:
        code = None
        try:
            body = json.loads(error.read(_MAX_CONTROL_FILE))
            code = body.get("error") if isinstance(body, dict) else None
        except Exception:
            pass
        finally:
            error.close()
        raise RouteError(code if isinstance(code, str) and code else f"http-{error.code}") from None
    except Exception:
        raise EndpointError(NOT_REACHABLE) from None
    try:
        return json.loads(raw)
    except ValueError:
        raise EndpointError(NOT_REACHABLE) from None


def control_call(control: Control, route: str, **params) -> dict:
    try:
        answer = get_json(control.url(route, token=control.token, **params))
    except RouteError as error:
        if error.code == "http-404":
            raise EndpointError(NOT_REACHABLE) from None
        raise
    if not isinstance(answer, dict):
        raise EndpointError(NOT_REACHABLE)
    return answer


def session_call(control: Control, session: str, route: str, **params):
    try:
        return get_json(control.url(route, token=session, **params))
    except RouteError as error:
        if error.code == "http-404":
            raise SessionError(SESSION_ENDED) from None
        raise


def session_gone(endpoint: Endpoint) -> bool:
    if endpoint.explicit or not endpoint.active:
        return False
    try:
        get_json(endpoint.active, timeout=2)
    except RouteError as error:
        return error.code == "http-404"
    except EndpointError:
        return False
    return False


def lost_error(endpoint: Endpoint) -> EndpointError:
    return SessionError(SESSION_ENDED) if session_gone(endpoint) else EndpointError(NOT_REACHABLE)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True
