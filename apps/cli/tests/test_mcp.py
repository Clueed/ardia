import json
import os
import queue
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ardia_cli import mcp
from tests.test_sessions import CONTROL_TOKEN, SESSION_TOKEN, Base, FakeArdia, connect_server

CLI_DIR = Path(__file__).resolve().parents[1]
WAIT = 10


class McpClient:
    def __init__(self, root: Path, *extra: str, env: dict | None = None):
        environment = dict(os.environ, ARDIA_DATA_DIR=str(root), **(env or {}))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "ardia_cli", "mcp", *extra],
            cwd=CLI_DIR, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.lines: queue.Queue = queue.Queue()
        self.raw: list[str] = []
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.raw.append(line)
            self.lines.put(json.loads(line))
        self.lines.put(None)

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> int:
        self.next_id += 1
        self.send({"id": self.next_id, "method": method, "params": params or {}})
        return self.next_id

    def answer(self, request_id: int, notes: list | None = None) -> dict:
        while True:
            message = self.lines.get(timeout=WAIT)
            if message is None:
                raise AssertionError("the server exited")
            if message.get("id") == request_id:
                return message
            if notes is not None:
                notes.append(message)

    def ask(self, method: str, params: dict | None = None, notes: list | None = None) -> dict:
        return self.answer(self.request(method, params), notes)

    def tool(self, name: str, arguments: dict | None = None, **params) -> dict:
        return self.ask("tools/call", {"name": name, "arguments": arguments or {}, **params})["result"]

    def close(self) -> str:
        self.process.stdin.close()
        self.process.wait(timeout=WAIT)
        err = self.process.stderr.read()
        self.process.stderr.close()
        self.process.stdout.close()
        return err


class Mcp(Base):
    def client(self, *extra: str, env: dict | None = None) -> McpClient:
        client = McpClient(self.root, *extra, env=env)
        self.addCleanup(lambda: client.process.poll() is None and client.close())
        answer = client.ask("initialize", {"protocolVersion": "2025-03-26", "clientInfo": {"name": "test-client", "version": "1"}, "capabilities": {}})
        self.assertEqual(answer["result"]["protocolVersion"], "2025-03-26")
        client.send({"method": "notifications/initialized"})
        return client

    def test_lists_its_tools_with_schemas(self):
        client = self.client()
        tools = client.ask("tools/list")["result"]["tools"]
        listing = json.loads(mcp.FORWARDED_TOOLS.read_text())
        forwarded = [name for name in listing["profiles"]["core"] if name not in mcp.DENIED_TOOLS]
        self.assertEqual([t["name"] for t in tools], [t["name"] for t in mcp.TOOLS] + forwarded)
        self.assertIn("agent_browser_snapshot", forwarded)
        self.assertNotIn("exec", [t["name"] for t in tools])
        self.assertNotIn("browse", [t["name"] for t in tools])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertEqual(client.ask("ping")["result"], {})
        self.assertEqual(client.ask("nope")["error"]["code"], -32601)
        self.assertEqual(client.ask("tools/call", {"name": "nope"})["error"]["code"], -32602)

    def test_session_tools_ask_for_connect_first(self):
        self.serve(lambda path, params: (200, {}))
        client = self.client()
        for name, arguments in (("run", {"command": "newTab"}), ("agent_browser_snapshot", {}), ("agent_browser_open", {"url": "https://example.com"}), ("disconnect", {}), ("rename", {"name": "x"})):
            with self.subTest(tool=name):
                result = client.tool(name, arguments)
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"], "session")
                self.assertIn("call connect first", result["content"][0]["text"])

    def test_connect_keeps_the_session_and_never_shows_it(self):
        def respond(path, params):
            if path == "/ardia/run":
                return (200, {"result": {"tab": 7}}) if params.get("token") == SESSION_TOKEN else (404, {})
            return connect_server([{"state": "allowed", "session": SESSION_TOKEN, "profile": "Scout", "kind": "agent"}])(path, params)

        fake = self.serve(respond)
        client = self.client()
        connected = client.tool("connect", {"name": "Scout", "new": True})
        self.assertEqual(json.loads(connected["content"][0]["text"]), {"profile": "Scout", "kind": "agent"})
        self.assertNotIn("structuredContent", connected)
        self.assertEqual(fake.routes("/ardia/connect")[0], {"token": CONTROL_TOKEN, "agent": "test-client", "new": "Scout"})
        ran = client.tool("run", {"command": "newTab:background"})
        self.assertEqual(json.loads(ran["content"][0]["text"]), {"result": {"tab": 7}})
        self.assertEqual(fake.routes("/ardia/run"), [{"token": SESSION_TOKEN, "command": "newTab", "arg": '"background"'}])
        client.close()
        self.assertFalse(any(SESSION_TOKEN in line or CONTROL_TOKEN in line for line in client.raw))

    def test_connect_to_an_owner_profile_reports_progress_while_it_waits(self):
        self.serve(connect_server([{"state": "pending"}, {"state": "allowed", "session": SESSION_TOKEN, "profile": "Work", "kind": "real"}]))
        client = self.client()
        notes: list = []
        answer = client.ask("tools/call", {"name": "connect", "arguments": {"name": "Work", "agent": "claude"}, "_meta": {"progressToken": "p1"}}, notes)
        self.assertEqual(json.loads(answer["result"]["content"][0]["text"]), {"profile": "Work", "kind": "real"})
        progress = [n for n in notes if n.get("method") == "notifications/progress"]
        self.assertEqual(progress[0]["params"]["progressToken"], "p1")
        self.assertIn("allow", progress[0]["params"]["message"])

    def test_sessions_it_opened_end_when_it_exits_and_given_ones_stay(self):
        def respond(path, params):
            if path == "/ardia/disconnect":
                return 200, {}
            return connect_server([{"state": "allowed", "session": SESSION_TOKEN, "profile": "Scout", "kind": "agent"}])(path, params)

        fake = self.serve(respond)
        client = self.client()
        client.tool("connect", {"name": "Scout", "new": True})
        client.close()
        self.assertEqual(fake.routes("/ardia/disconnect"), [{"token": SESSION_TOKEN}])

        given = self.client(env={"ARDIA_SESSION": SESSION_TOKEN})
        given.ask("ping")
        given.close()
        self.assertEqual(len(fake.routes("/ardia/disconnect")), 1)

    def test_a_cancelled_connect_withdraws_the_request(self):
        fake = self.serve(connect_server([{"state": "pending"}]))
        client = self.client()
        request = client.request("tools/call", {"name": "connect", "arguments": {"name": "Work"}, "_meta": {"progressToken": "p"}})
        note = client.lines.get(timeout=WAIT)
        self.assertEqual(note["method"], "notifications/progress")
        client.send({"method": "notifications/cancelled", "params": {"requestId": request}})
        self.assertEqual(client.ask("ping")["result"], {})
        client.close()
        cancels = [p for p in fake.routes("/ardia/connect") if p.get("cancel") == "1"]
        self.assertEqual(cancels, [{"token": CONTROL_TOKEN, "request": "r1", "cancel": "1"}])

    def test_refusals_and_ended_sessions_are_tool_errors(self):
        def respond(path, params):
            if params.get("command") == "nope":
                return 400, {"error": "unknown_command", "message": "no command nope"}
            return 404, {}

        self.serve(respond)
        client = self.client(env={"ARDIA_SESSION": SESSION_TOKEN})
        refused = client.tool("run", {"command": "nope"})
        self.assertEqual(refused["structuredContent"], {"error": "refused", "code": "unknown_command", "message": "no command nope"})
        ended = client.tool("run", {"command": "newTab"})
        self.assertEqual(ended["structuredContent"]["error"], "session")
        self.assertIn("has ended", ended["structuredContent"]["message"])

    def test_refusals_read_as_sentences(self):
        def respond(path, params):
            if path == "/ardia/profiles":
                return 200, {"profiles": [{"name": "Scout", "kind": "agent"}]}
            return 409, {"error": "name-taken"}

        self.serve(respond)
        result = self.client().tool("connect", {"name": "scout", "new": True})
        self.assertEqual(result["structuredContent"], {"error": "refused", "code": "name-taken", "message": "a profile is already named 'Scout': pick another name, or connect to 'Scout' to use it"})

    def test_unreachable_without_ardia(self):
        result = self.client().tool("connect", {"name": "Scout", "new": True})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "unreachable")

    def test_bad_arguments_and_unknown_events(self):
        client = self.client()
        self.assertEqual(client.ask("tools/call", {"name": "tabs", "arguments": {"extra": 1}})["error"]["code"], -32602)
        result = client.tool("wait_for_event", {"events": ["tab.nope"]})
        self.assertEqual(result["structuredContent"]["code"], "unknown_event")

    def test_the_deny_list_holds_for_every_profile(self):
        client = self.client("--tools", "all")
        names = [t["name"] for t in client.ask("tools/list")["result"]["tools"]]
        listing = json.loads(mcp.FORWARDED_TOOLS.read_text())
        self.assertEqual(len(names), len(mcp.TOOLS) + len(set(listing["profiles"]["all"]) - mcp.DENIED_TOOLS))
        for denied in ("agent_browser_install", "agent_browser_upgrade", "agent_browser_doctor", "agent_browser_connect",
                       "agent_browser_dashboard_start", "agent_browser_chat", "agent_browser_confirm", "agent_browser_deny",
                       "agent_browser_profiles", "agent_browser_skills_get", "agent_browser_tools_profiles", "agent_browser_get_cdp_url"):
            self.assertIn(denied, listing["profiles"]["all"])
            self.assertNotIn(denied, names)
        self.assertTrue(mcp.DENIED_TOOLS <= set(listing["profiles"]["all"]))
        for tool in client.ask("tools/list")["result"]["tools"]:
            self.assertFalse(mcp.DROPPED_ARGUMENTS & set(tool["inputSchema"].get("properties", {})), tool["name"])

    def test_an_unknown_tools_profile_stops_the_server(self):
        done = subprocess.run([sys.executable, "-m", "ardia_cli", "mcp", "--tools", "core,nope"], cwd=CLI_DIR, input="",
                              capture_output=True, text=True, timeout=WAIT, env=dict(os.environ, ARDIA_DATA_DIR=str(self.root)))
        self.assertEqual(done.returncode, 64)
        self.assertIn("nope", done.stderr)


FAKE_AGENT_BROWSER = """\
import json, os, sys
record = os.environ["FAKE_RECORD"]
with open(record, "a") as handle:
    handle.write(json.dumps({"pid": os.getpid(), "argv": sys.argv[1:], "env": dict(os.environ)}) + "\\n")
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}
    elif method == "tools/call":
        params = message["params"]
        token = params.get("_meta", {}).get("progressToken")
        if token is not None:
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": token, "progress": 1}}), flush=True)
        if params["name"] == "agent_browser_eval":
            os._exit(1)
        failed = params["name"] == "agent_browser_click"
        text = "clicked nothing" if failed else "page at " + os.environ["AGENT_BROWSER_CDP"]
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "no"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
"""


class Forwarding(Base):
    client = Mcp.client

    def setUp(self):
        super().setUp()
        self.record = self.root / "children.jsonl"
        self.program = self.root / "agent-browser"
        self.program.write_text("#!" + sys.executable + "\n" + FAKE_AGENT_BROWSER)
        self.program.chmod(0o755)
        self.alive = True

        def respond(path, params):
            if path == "/ardia/disconnect":
                return 200, {}
            if path == "/ardia/active":
                return (200, {"targetId": "T1"}) if self.alive and params.get("token") == SESSION_TOKEN else (404, {"error": "not-found"})
            return connect_server([{"state": "allowed", "session": SESSION_TOKEN, "profile": "Scout", "kind": "agent"}])(path, params)

        self.fake = self.serve(respond)

    def connected(self) -> McpClient:
        client = self.client(env={"ARDIA_AGENT_BROWSER": str(self.program), "FAKE_RECORD": str(self.record)})
        client.tool("connect", {"name": "Scout", "new": True})
        return client

    def children(self) -> list[dict]:
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def wait_gone(self, pid: int) -> None:
        import time

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail(f"agent-browser {pid} still runs")

    def test_starts_on_the_first_call_with_the_session_in_its_environment(self):
        import hashlib

        client = self.connected()
        self.assertEqual(self.children(), [])
        notes: list = []
        answer = client.ask("tools/call", {"name": "agent_browser_snapshot", "arguments": {"interactive": True}, "_meta": {"progressToken": "p9"}}, notes)
        result = answer["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["text"], f"page at ws://127.0.0.1:{self.fake.port}/devtools/browser/abc?token=***")
        self.assertEqual([n["params"]["progressToken"] for n in notes if n.get("method") == "notifications/progress"], ["p9"])
        [child] = self.children()
        self.assertEqual(child["argv"], ["mcp", "--tools", "core", "--config", str(CLI_DIR / "ardia_cli" / "agent-browser.json")])
        self.assertNotIn(SESSION_TOKEN, json.dumps(child["argv"]))
        env = child["env"]
        self.assertEqual(env["AGENT_BROWSER_CDP"], f"ws://127.0.0.1:{self.fake.port}/devtools/browser/abc?token={SESSION_TOKEN}")
        self.assertEqual(env["AGENT_BROWSER_SESSION"], hashlib.sha256(SESSION_TOKEN.encode()).hexdigest()[:16])
        self.assertEqual(env["AGENT_BROWSER_NO_VERSION_CHECK"], "1")
        client.tool("agent_browser_get_url")
        self.assertEqual(len(self.children()), 1)
        self.assertEqual(json.loads(client.tool("disconnect")["content"][0]["text"]), {"disconnected": True})
        self.wait_gone(child["pid"])
        after = client.tool("agent_browser_get_url")
        self.assertEqual(after["structuredContent"]["error"], "session")
        self.assertIn("call connect first", after["content"][0]["text"])
        client.close()
        self.assertFalse(any(SESSION_TOKEN in line or CONTROL_TOKEN in line for line in client.raw))

    def test_it_stops_when_the_server_exits(self):
        client = self.connected()
        client.tool("agent_browser_get_url")
        [child] = self.children()
        client.close()
        self.wait_gone(child["pid"])

    def test_a_dead_child_errors_once_and_restarts(self):
        client = self.connected()
        died = client.tool("agent_browser_eval", {"script": "1"})
        self.assertTrue(died["isError"])
        self.assertEqual(died["structuredContent"]["code"], "agent_browser")
        self.assertFalse(client.tool("agent_browser_get_url")["isError"])
        self.assertEqual(len(self.children()), 2)

    def test_errors_after_the_session_ended_say_so(self):
        client = self.connected()
        self.assertEqual(client.tool("agent_browser_click", {"selector": "@e1"})["content"][0]["text"], "clicked nothing")
        self.alive = False
        ended = client.tool("agent_browser_click", {"selector": "@e1"})
        self.assertEqual(ended["structuredContent"]["error"], "session")
        self.assertIn("has ended", ended["structuredContent"]["message"])
        self.wait_gone(self.children()[0]["pid"])

    def test_arguments_that_move_it_are_refused(self):
        client = self.connected()
        for extra in (["--cdp", "ws://elsewhere:1/devtools/browser/x"], ["--config", "x.json"], ["--auto-connect"], ["--session=other"]):
            with self.subTest(extra=extra):
                refused = client.tool("agent_browser_snapshot", {"extraArgs": extra})
                self.assertEqual(refused["structuredContent"]["code"], "refused_argument")
        self.assertEqual(client.ask("tools/call", {"name": "agent_browser_snapshot", "arguments": {"session": "x"}})["error"]["code"], -32602)
        self.assertEqual(self.children(), [])


if __name__ == "__main__":
    unittest.main()
