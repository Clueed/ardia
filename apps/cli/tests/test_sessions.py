import contextlib
import io
import json
import logging
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ardia_cli import api, browsing, cli, endpoint, redact, sessions

CONTROL_TOKEN = "control-" + "c" * 40
SESSION_TOKEN = "session-" + "s" * 40
WEBKIT_NOW = int((time.time() + browsing.WEBKIT_EPOCH_OFFSET) * 1_000_000)


class FakeArdia:
    def __init__(self, respond):
        self.respond = respond
        self.calls: list[tuple[str, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = urlsplit(self.path)
                params = {key: values[0] for key, values in parse_qs(parts.query).items()}
                fake.calls.append((parts.path, params))
                status, body = fake.respond(parts.path, params)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def routes(self, path: str) -> list[dict]:
        return [params for called, params in self.calls if called == path]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ardia-cli-sessions-")).resolve()
        (self.root / "Chromium").mkdir()
        self.addCleanup(shutil.rmtree, self.root, True)
        patch = mock.patch.dict(os.environ, {"ARDIA_DATA_DIR": str(self.root)}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("ARDIA_SESSION", "ARDIA_AGENT", "ARDIA_CDP_URL"):
            os.environ.pop(name, None)

    def serve(self, respond) -> FakeArdia:
        fake = FakeArdia(respond)
        self.addCleanup(fake.close)
        self.write_control(fake.port)
        return fake

    def write_control(self, port: int):
        path = self.root / "ArdiaGateway.json"
        path.write_text(json.dumps({"port": port, "browser": "/devtools/browser/abc", "token": CONTROL_TOKEN, "pid": os.getpid(), "generation": 1}))
        path.chmod(0o600)

    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(list(argv))
        return status, out.getvalue(), err.getvalue()


def connect_server(answers: list[dict], start=None):
    pending = list(answers)

    def respond(path, params):
        if path == "/ardia/connect" and "cancel" in params:
            return 200, {}
        if path == "/ardia/connect" and "request" in params:
            return 200, pending.pop(0) if len(pending) > 1 else pending[0]
        if path == "/ardia/connect":
            return start or (200, {"request": "r1"})
        return 404, {}

    return respond


class Connect(Base):
    def test_allowed_prints_only_the_session(self):
        fake = self.serve(connect_server([{"state": "pending"}, {"state": "pending"}, {"state": "allowed", "session": SESSION_TOKEN, "profile": "Work", "kind": "real"}]))
        with mock.patch.object(api, "POLL_INTERVAL", 0.01):
            status, out, err = self.run_cli("connect", "Work", "--agent", "claude-code")
        self.assertEqual(status, 0)
        self.assertEqual(out, SESSION_TOKEN + "\n")
        self.assertIn(sessions.WAITING, err)
        self.assertNotIn(SESSION_TOKEN, err)
        self.assertNotIn(CONTROL_TOKEN, out + err)
        first = fake.routes("/ardia/connect")[0]
        self.assertEqual(first, {"token": CONTROL_TOKEN, "agent": "claude-code", "profile": "Work"})

    def test_new_with_json_and_agent_from_env(self):
        os.environ["ARDIA_AGENT"] = "codex"
        fake = self.serve(connect_server([{"state": "allowed", "session": SESSION_TOKEN, "profile": "LinkedIn", "kind": "agent"}]))
        status, out, err = self.run_cli("connect", "--new", "LinkedIn", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out), {"session": SESSION_TOKEN, "profile": "LinkedIn", "kind": "agent"})
        self.assertNotIn(sessions.WAITING, err)
        self.assertEqual(fake.routes("/ardia/connect")[0]["new"], "LinkedIn")
        self.assertEqual(fake.routes("/ardia/connect")[0]["agent"], "codex")

    def test_default_agent_name(self):
        fake = self.serve(connect_server([{"state": "allowed", "session": SESSION_TOKEN}]))
        self.assertEqual(self.run_cli("connect", "--new", "x")[0], 0)
        self.assertEqual(fake.routes("/ardia/connect")[0]["agent"], api.DEFAULT_AGENT)

    def test_denied(self):
        self.serve(connect_server([{"state": "pending"}, {"state": "denied"}]))
        with mock.patch.object(api, "POLL_INTERVAL", 0.01):
            status, out, err = self.run_cli("connect", "Work")
        self.assertEqual(status, sessions.DENIED_EXIT)
        self.assertEqual(out, "")
        self.assertIn("denied", err)

    def test_expired(self):
        self.serve(connect_server([{"state": "expired"}]))
        status, out, _ = self.run_cli("connect", "Work")
        self.assertEqual(status, sessions.EXPIRED_EXIT)
        self.assertEqual(out, "")

    def test_no_answer_in_time_cancels(self):
        fake = self.serve(connect_server([{"state": "pending"}]))
        with mock.patch.object(api, "CONNECT_WAIT", 0.1), mock.patch.object(api, "POLL_INTERVAL", 0.02):
            status, _, _ = self.run_cli("connect", "Work")
        self.assertEqual(status, sessions.EXPIRED_EXIT)
        self.assertTrue(any(p.get("cancel") == "1" for p in fake.routes("/ardia/connect")))

    def test_ctrl_c_cancels(self):
        fake = self.serve(connect_server([{"state": "pending"}]))

        def interrupt(_seconds):
            raise KeyboardInterrupt

        with mock.patch.object(api.time, "sleep", interrupt):
            status, out, err = self.run_cli("connect", "Work")
        self.assertEqual(status, 130)
        self.assertEqual(out, "")
        cancels = [p for p in fake.routes("/ardia/connect") if p.get("cancel") == "1"]
        self.assertEqual(cancels, [{"token": CONTROL_TOKEN, "request": "r1", "cancel": "1"}])

    def test_terminate_and_hangup_cancel(self):
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum.name):
                fake = self.serve(connect_server([{"state": "pending"}]))
                before = signal.getsignal(signum)

                def stop(_seconds, signum=signum):
                    signal.raise_signal(signum)

                with mock.patch.object(api.time, "sleep", stop):
                    status, out, err = self.run_cli("connect", "Work")
                self.assertEqual(status, 128 + signum)
                self.assertEqual(out, "")
                self.assertIn("cancelled", err)
                cancels = [p for p in fake.routes("/ardia/connect") if p.get("cancel") == "1"]
                self.assertEqual(cancels, [{"token": CONTROL_TOKEN, "request": "r1", "cancel": "1"}])
                self.assertIs(signal.getsignal(signum), before)

    def test_name_taken_names_the_existing_profile(self):
        def respond(path, params):
            if path == "/ardia/profiles":
                return 200, {"profiles": [{"name": "Personal", "kind": "real"}, {"name": "Scout", "kind": "agent"}]}
            return 409, {"error": "name-taken"}

        self.serve(respond)
        status, _, err = self.run_cli("connect", "--new", " scout")
        self.assertEqual(status, 1)
        self.assertIn("already named 'Scout'", err)
        self.assertIn("ardia connect 'Scout' to use it", err)

    def test_route_errors_are_one_line(self):
        for code, needle in (("no-such-profile", "no profile is named 'Nope'"), ("name-taken", "already named"), ("bad-name", "isn't a usable")):
            with self.subTest(code=code):
                self.serve(connect_server([], start=(404 if code == "no-such-profile" else 409, {"error": code})))
                status, out, err = self.run_cli("connect", "Nope")
                self.assertEqual(status, 1)
                self.assertEqual(out, "")
                self.assertIn(needle, err)
                self.assertEqual(err.count("\n"), 1)

    def test_unreachable(self):
        engine_file = self.root / "Chromium" / "ArdiaControl.json"
        engine_file.write_text(json.dumps({"port": 1, "browser": "/devtools/browser/abc", "token": CONTROL_TOKEN, "pid": os.getpid(), "generation": 1}))
        engine_file.chmod(0o600)
        status, _, err = self.run_cli("connect", "Work")
        self.assertEqual(status, 2)
        self.assertIn(endpoint.NOT_REACHABLE, err)
        self.write_control(1)
        self.assertEqual(self.run_cli("connect", "Work")[0], 2)

    def test_unknown_control_token_is_unreachable(self):
        self.serve(lambda path, params: (404, {}))
        self.assertEqual(self.run_cli("connect", "Work")[0], 2)

    def test_needs_a_name(self):
        self.assertEqual(self.run_cli("connect")[0], 1)
        self.assertEqual(self.run_cli("connect", "a", "--new", "b")[0], 1)


class Profiles(Base):
    def test_lists(self):
        listed = [{"name": "Work", "kind": "real", "connected": 0}, {"name": "LinkedIn", "kind": "agent", "connected": 2}]
        fake = self.serve(lambda path, params: (200, {"profiles": listed}) if path == "/ardia/profiles" else (404, {}))
        status, out, _ = self.run_cli("profiles")
        self.assertEqual(status, 0)
        self.assertEqual(out, "Work (real)\nLinkedIn (agent, 2 connected)\n")
        status, out, _ = self.run_cli("profiles", "--json")
        self.assertEqual(json.loads(out), {"profiles": listed})
        self.assertEqual(fake.routes("/ardia/profiles")[0], {"token": CONTROL_TOKEN})


class Sessions(Base):
    def session_server(self, rename_error=None):
        def respond(path, params):
            if params.get("token") != SESSION_TOKEN:
                return 404, {"error": "not-found"}
            if path == "/ardia/rename" and rename_error:
                return 409, {"error": rename_error}
            return 200, {} if path != "/ardia/active" else None

        return self.serve(respond)

    def test_missing_session_is_refused(self):
        self.session_server()
        for argv in (("exec", "1"), ("disconnect",), ("rename", "x")):
            with self.subTest(argv=argv):
                status, out, err = self.run_cli(*argv)
                self.assertEqual(status, endpoint.SESSION_EXIT)
                self.assertIn("ardia connect", err)
                self.assertEqual(err.count("\n"), 1)

    def test_test_servers_need_no_session(self):
        status, _, err = self.run_cli("exec", "--port", "1", "1")
        self.assertEqual(status, 2)
        self.assertNotIn("ardia connect", err)

    def test_disconnect_and_rename(self):
        fake = self.session_server()
        self.assertEqual(self.run_cli("disconnect", "--session", SESSION_TOKEN)[:2], (0, "disconnected\n"))
        os.environ["ARDIA_SESSION"] = SESSION_TOKEN
        self.assertEqual(self.run_cli("rename", "New name")[:2], (0, "renamed to New name\n"))
        self.assertEqual(fake.routes("/ardia/rename"), [{"token": SESSION_TOKEN, "name": "New name"}])

    def test_rename_refused(self):
        self.session_server(rename_error="not-agent")
        status, _, err = self.run_cli("rename", "x", "--session", SESSION_TOKEN)
        self.assertEqual(status, 1)
        self.assertIn("only agent profiles", err)

    def test_ended_session(self):
        self.session_server()
        other = "session-" + "e" * 40
        status, out, err = self.run_cli("disconnect", "--session", other)
        self.assertEqual(status, endpoint.SESSION_EXIT)
        self.assertIn("has ended", err)
        self.assertNotIn(other, out + err)

    def test_exec_with_an_ended_session(self):
        self.session_server()
        other = "session-" + "f" * 40
        status, out, err = self.run_cli("exec", "--session", other, "1")
        self.assertEqual(status, endpoint.SESSION_EXIT)
        self.assertIn("has ended", err)
        self.assertNotIn(other, out + err)

    def test_exec_endpoint_uses_the_session(self):
        fake = self.session_server()
        found = endpoint.resolve(session=SESSION_TOKEN)
        self.assertTrue(found.ws.startswith(f"ws://127.0.0.1:{fake.port}/devtools/browser/abc?token="))
        self.assertIn(SESSION_TOKEN, found.ws)
        self.assertNotIn(CONTROL_TOKEN, found.ws + (found.active or ""))
        self.assertEqual(found.active, f"http://127.0.0.1:{fake.port}/ardia/active?token={SESSION_TOKEN}")
        self.assertFalse(endpoint.session_gone(found))


class Browse(Base):
    def session_server(self):
        def respond(path, params):
            if params.get("token") != SESSION_TOKEN:
                return 404, {"error": "not-found"}
            return 200, {"targetId": "T1"} if path == "/ardia/active" else {}

        return self.serve(respond)

    def test_endpoint_has_the_gateway_instance(self):
        self.session_server()
        found = endpoint.resolve(session=SESSION_TOKEN)
        self.assertEqual(found.instance, f"{os.getpid()}:1:/devtools/browser/abc")

    def test_needs_an_ardia_session(self):
        self.session_server()
        for argv in (("browse", "open", "example.com"), ("browse", "--ardia-session", "short", "snapshot")):
            with self.subTest(argv=argv):
                status, out, err = self.run_cli(*argv)
                self.assertEqual(status, endpoint.SESSION_EXIT)
                self.assertIn("ardia connect", out + err)

    def test_session_namespaces_are_not_ardia_sessions(self):
        self.session_server()
        status, _, err = self.run_cli("browse", "--session", SESSION_TOKEN[:20], "open", "example.com")
        self.assertEqual(status, endpoint.SESSION_EXIT)
        self.assertIn("Connect first", err)

    def test_each_ardia_session_gets_its_own_daemon(self):
        from ardia_cli.browse import client

        first = client.endpoint_key(None, None, self.root, SESSION_TOKEN)
        second = client.endpoint_key(None, None, self.root, "session-" + "t" * 40)
        self.assertNotEqual(first[0], second[0])
        self.assertNotIn(SESSION_TOKEN, first[0] + first[1])

    def test_tab_active_follows_the_session(self):
        import asyncio
        import types

        from ardia_cli.browse.commands import user_active_tab
        from ardia_cli.browse.errors import SessionEnded

        fake = self.session_server()
        live = types.SimpleNamespace(endpoint=endpoint.resolve(session=SESSION_TOKEN))
        self.assertEqual(asyncio.run(user_active_tab(live)), "T1")
        self.assertEqual(fake.routes("/ardia/active"), [{"token": SESSION_TOKEN}])
        ended = types.SimpleNamespace(endpoint=endpoint.resolve(session="session-" + "g" * 40))
        with self.assertRaises(SessionEnded) as caught:
            asyncio.run(user_active_tab(ended))
        self.assertEqual(caught.exception.exit_code, endpoint.SESSION_EXIT)


class CommandHooks(Base):
    def gateway(self):
        def respond(path, params):
            if path != "/ardia/run" or params.get("token") != SESSION_TOKEN:
                return 404, {}
            if params.get("command") == "togglePin":
                return 403, {"error": "refused", "message": "togglePin reaches beyond one profile, so a session can't run it."}
            return 200, {"result": {"ok": True}}

        return self.serve(respond)

    def fire(self, command: str, event: dict) -> str:
        import asyncio
        import types

        from ardia_cli import hooks

        stream = io.StringIO()
        service = types.SimpleNamespace(socket_path=self.root / "ArdiaControl.sock", scopes={"reload": "page", "newTab": "window"})
        runner = hooks.CommandRunner(hooks.hook_from({"name": "h", "on": "tab.activated", "command": command}), hooks.Log(stream=stream), service)
        asyncio.run(runner._run(event))
        return stream.getvalue()

    def test_runs_through_the_gateway_with_the_session(self):
        fake = self.gateway()
        os.environ["ARDIA_SESSION"] = SESSION_TOKEN
        self.assertEqual(self.fire("reload", {"event": "tab.activated", "data": {"windowId": "2", "tabId": "9"}}), "")
        self.assertEqual(self.fire("newTab", {"event": "tab.activated", "data": {"windowId": "2", "tabId": "9"}}), "")
        self.assertEqual(fake.routes("/ardia/run"), [
            {"token": SESSION_TOKEN, "command": "reload", "window": "2", "tab": "9"},
            {"token": SESSION_TOKEN, "command": "newTab", "window": "2"},
        ])

    def test_without_a_session_nothing_runs(self):
        fake = self.gateway()
        logged = self.fire("reload", {"event": "tab.activated", "data": {}})
        self.assertIn("ARDIA_SESSION", logged)
        self.assertEqual(fake.routes("/ardia/run"), [])

    def test_a_refused_command_says_why(self):
        self.gateway()
        os.environ["ARDIA_SESSION"] = SESSION_TOKEN
        logged = self.fire("togglePin", {"event": "tab.activated", "data": {}})
        self.assertIn("a session can't run it", logged)
        self.assertNotIn(SESSION_TOKEN, logged)


class Redaction(Base):
    def test_session_tokens_are_secrets(self):
        token = "session-" + "r" * 40
        endpoint.require_session(token)
        self.assertNotIn(token, redact.redact(f"lost {token} at ws://x/?a={token}"))
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        redact.install_log_redaction()
        logger = logging.getLogger("ardia-test-redaction")
        handler = Keep()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        try:
            raise RuntimeError(f"boom {token}")
        except RuntimeError:
            logger.exception("failed with %s", token)
        self.assertTrue(records)
        self.assertNotIn(token, records[0])

    def test_connect_redacts_stderr_but_prints_the_session(self):
        token = "session-" + "q" * 40

        def respond(path, params):
            if "request" in params:
                return 200, {"state": "allowed", "session": token}
            return 200, {"request": "r1"}

        self.serve(respond)
        with mock.patch.object(sessions, "WAITING", "waiting"):
            status, out, err = self.run_cli("connect", "Work")
        self.assertEqual((status, out), (0, token + "\n"))
        self.assertNotIn(token, err)
        self.assertNotIn(token, redact.redact(f"x {token}"))


def make_history(folder: Path, urls: list[str]):
    folder.mkdir(parents=True)
    connection = sqlite3.connect(folder / "History")
    connection.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, hidden INTEGER)")
    connection.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER, transition INTEGER)")
    for index, url in enumerate(urls, 1):
        connection.execute("INSERT INTO urls VALUES (?, ?, ?, 1, 0)", (index, url, url))
        connection.execute("INSERT INTO visits VALUES (?, ?, ?, 0)", (index, index, WEBKIT_NOW - index))
    connection.commit()
    connection.close()


class AgentProfiles(Base):
    def setUp(self):
        super().setUp()
        self.write_control(1)
        session = {
            "version": 2,
            "profiles": {
                "default": {"name": "Me"},
                "work": {"name": "Work", "dataId": "w1"},
                "bot": {"name": "Bot", "kind": "agent", "dataId": "b1"},
            },
            "profileOrder": ["bot", "default", "work"],
            "windows": [
                {"id": "w", "incognito": False, "tabIds": ["t1", "t2", "t3", "t4", "t5"]},
                {"id": "w2", "incognito": False, "tabIds": ["t1"]},
                {"id": "i", "incognito": True, "tabIds": ["t6"]},
            ],
            "tabs": [
                {"id": "t1", "profileId": "default", "url": "https://fav.example/", "title": "Fav", "pinned": True, "pinKey": "k1"},
                {"id": "t2", "profileId": "default", "url": "https://open.example/", "title": "Open"},
                {"id": "t3", "profileId": "bot", "url": "https://bot.example/", "title": "Bot tab", "pinned": True},
                {"id": "t4", "profileId": "bot", "url": "https://bot2.example/", "title": "Bot tab 2"},
                {"id": "t5", "profileId": "work", "url": "https://work.example/", "title": "Work", "customTitle": "Mine"},
                {"id": "t6", "profileId": "incognito:default", "url": "https://secret.example/", "title": "Secret"},
            ],
            "groups": [],
            "parkedPins": {"bot": {"tabs": [{"id": "p1", "url": "https://parked-bot.example/", "title": "P"}], "groups": []}},
        }
        (self.root / "session.json").write_text(json.dumps(session))
        make_history(self.root / "Chromium" / "Default", ["https://me.example/"])
        make_history(self.root / "Chromium" / "Profile w1", ["https://work.example/"])
        make_history(self.root / "Chromium" / "Profile b1", ["https://bot.example/"])
        make_history(self.root / "Chromium" / "Profile zz", ["https://unknown.example/"])

    def test_history_skips_agent_profiles(self):
        rows = browsing.history(self.root, days=1)
        self.assertEqual(sorted((row["profile"], row["url"]) for row in rows), [("Me", "https://me.example/"), ("Work", "https://work.example/")])
        for name in ("Bot", "Profile b1", "Profile zz"):
            with self.assertRaises(browsing.BrowsingDataError):
                browsing.history(self.root, profile=name)

    def test_history_needs_control(self):
        (self.root / "ArdiaGateway.json").unlink()
        with self.assertRaises(browsing.BrowsingDataError):
            browsing.history(self.root)
        with self.assertRaises(browsing.BrowsingDataError):
            browsing.history(None)

    def test_history_refuses_a_symlinked_session(self):
        real = self.root / "real.json"
        (self.root / "session.json").rename(real)
        (self.root / "session.json").symlink_to(real)
        with self.assertRaises(browsing.BrowsingDataError):
            browsing.history(self.root)


if __name__ == "__main__":
    unittest.main()
