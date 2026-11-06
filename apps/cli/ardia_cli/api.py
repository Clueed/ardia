import os
import time
from contextlib import contextmanager
from pathlib import Path

from ardia_cli import control
from ardia_cli.endpoint import (
    EndpointError,
    RouteError,
    RouteLost,
    SessionError,
    control_call,
    data_root,
    get_json,
    require_control,
    require_session,
    run_command,
    session_call,
)
from ardia_cli.redact import add_secret

DEFAULT_AGENT = "agent"
POLL_INTERVAL = 0.25
CONNECT_WAIT = 120
CANCEL_TIMEOUT = 2
NEEDS_DATA_DIR = "{what} needs --data-dir or $ARDIA_DATA_DIR when --port, --ws or $ARDIA_CDP_URL picks the browser"


class ArdiaError(Exception):
    kind = "error"

    def __init__(self, message: str, code: str | None = None):
        Exception.__init__(self, message)
        self.message = message
        self.code = code or self.kind


class Unreachable(ArdiaError, control.Unreachable):
    kind = "unreachable"
    sent = False


class OutcomeUnknown(Unreachable):
    kind = "outcome_unknown"
    sent = True


class SessionGone(ArdiaError, SessionError):
    kind = "session"


class Refused(ArdiaError, control.MethodError):
    kind = "refused"


class Denied(ArdiaError):
    kind = "denied"


class Expired(ArdiaError):
    kind = "expired"


@contextmanager
def translated():
    try:
        yield
    except ArdiaError:
        raise
    except SessionError as error:
        raise SessionGone(str(error)) from None
    except RouteLost as error:
        raise (OutcomeUnknown if error.sent else Unreachable)(str(error)) from None
    except EndpointError as error:
        raise Unreachable(str(error)) from None
    except RouteError as error:
        raise Refused(error.message, error.code) from None
    except control.MethodError as error:
        raise Refused(error.message, error.code) from None
    except control.Unreachable as error:
        raise (OutcomeUnknown if getattr(error, "sent", False) else Unreachable)(str(error)) from None


def profile_row(profile: dict) -> dict:
    return {
        "name": str(profile.get("name", "")),
        "kind": "agent" if profile.get("kind") == "agent" else "real",
        "connected": int(profile.get("connected") or 0),
    }


class Ardia:
    def __init__(self, root: Path | None, session: str | None = None):
        self.root = root
        self.session = session

    @classmethod
    def at(cls, data_dir: str | None = None, session: str | None = None) -> "Ardia":
        return cls(data_root(data_dir), session)

    def _root(self, what: str) -> Path:
        if self.root is None:
            raise Unreachable(NEEDS_DATA_DIR.format(what=what))
        return self.root

    def _gateway(self, what: str):
        return require_control(self._root(what))

    def _token(self) -> str:
        return require_session(self.session)

    def profiles(self) -> list[dict]:
        with translated():
            answer = control_call(self._gateway("profiles()"), "profiles")
        return [profile_row(p) for p in answer.get("profiles") or [] if isinstance(p, dict)]

    def connect(self, name: str, new: bool = False, agent: str | None = None, on_waiting=None, sleep=None) -> dict:
        agent = (agent or os.environ.get("ARDIA_AGENT") or "").strip() or DEFAULT_AGENT
        target = {"new": name} if new else {"profile": name}
        gateway = request = None
        try:
            with translated():
                gateway = self._gateway("connect()")
                request = control_call(gateway, "connect", agent=agent, **target).get("request")
                if not isinstance(request, str) or not request:
                    raise Unreachable("Ardia gave no request id")
                if not new and on_waiting is not None:
                    on_waiting()
                state = self._wait_for_answer(gateway, request, sleep or time.sleep)
        except BaseException:
            if request:
                self._cancel(gateway, request)
            raise
        if state is None:
            self._cancel(gateway, request)
            state = {"state": "expired"}
        if state.get("state") == "denied":
            raise Denied(f"the owner denied {agent!r} the use of {name!r}")
        if state.get("state") != "allowed":
            raise Expired(f"no answer within {CONNECT_WAIT} s, so the request expired")
        session = state.get("session")
        if not isinstance(session, str) or not session:
            raise Unreachable("Ardia allowed it but sent no session")
        add_secret(session)
        self.session = session
        return {"session": session, "profile": state.get("profile") or name, "kind": state.get("kind") or ("agent" if new else "real")}

    def _wait_for_answer(self, gateway, request: str, sleep) -> dict | None:
        deadline = time.monotonic() + CONNECT_WAIT
        while True:
            try:
                state = control_call(gateway, "connect", request=request)
            except RouteError:
                return {"state": "expired"}
            if state.get("state") != "pending":
                return state
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            sleep(min(POLL_INTERVAL, remaining))

    def _cancel(self, gateway, request: str) -> None:
        try:
            get_json(gateway.url("connect", token=gateway.token, request=request, cancel=1), timeout=CANCEL_TIMEOUT)
        except (Exception, KeyboardInterrupt):
            pass

    def disconnect(self) -> None:
        with translated():
            session_call(self._gateway("disconnect()"), self._token(), "disconnect")

    def rename(self, name: str) -> None:
        with translated():
            session_call(self._gateway("rename()"), self._token(), "rename", name=name)

    def run(self, command: str, arg=None, window=None, tab=None):
        if arg is None and ":" in command:
            command, arg = command.split(":", 1)
        with translated():
            return run_command(self._gateway("run()"), self._token(), command, arg, window, tab)

    async def _control_call(self, method: str, params=None, timeout=control.CALL_TIMEOUT):
        with translated():
            connection = await control.connect(self._root(f"{method}()") / control.SOCKET_FILE)
            try:
                return await connection.call(method, params, timeout)
            finally:
                await connection.close()

    async def commands(self, timeout=control.CALL_TIMEOUT) -> list:
        return await self._control_call("commands", timeout=timeout)

    async def windows(self) -> list:
        return await self._control_call("windows")

    async def events(self, *names: str, full_urls: bool = False, idle: int | None = None):
        wanted = control.check_events(names) or ["*"]
        extra = {}
        if full_urls:
            extra["fullUrls"] = True
        if idle is not None:
            extra["idle"] = {"tab": [idle], "user": [idle]}
        with translated():
            connection = await control.connect(self._root("events()") / control.SOCKET_FILE)
        try:
            with translated():
                await connection.subscribe(wanted, extra or None)
            while True:
                with translated():
                    event = await connection.next_event()
                yield event
        finally:
            await connection.close()

    async def pinned(self) -> list[dict]:
        from ardia_cli import browsing

        return await browsing.run_bounded(browsing.pinned, self.root)

    async def open_tabs(self, profile: str | None = None) -> list[dict]:
        from ardia_cli import browsing

        return await browsing.run_bounded(browsing.open_tabs, self.root, profile=profile)

    async def history(self, days: float = 1, limit: int | None = 200, profile: str | None = None, domains: bool = False) -> list[dict]:
        from ardia_cli import browsing

        return await browsing.run_bounded(browsing.history, self.root, days=days, limit=limit, profile=profile, domains=domains)

