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
        self.assertEqual([t["name"] for t in tools], [t["name"] for t in mcp.TOOLS])
        self.assertNotIn("exec", [t["name"] for t in tools])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertEqual(client.ask("ping")["result"], {})
        self.assertEqual(client.ask("nope")["error"]["code"], -32601)
        self.assertEqual(client.ask("tools/call", {"name": "nope"})["error"]["code"], -32602)

    def test_session_tools_ask_for_connect_first(self):
        self.serve(lambda path, params: (200, {}))
        client = self.client()
        for name, arguments in (("run", {"command": "newTab"}), ("browse", {"args": ["snapshot"]}), ("disconnect", {}), ("rename", {"name": "x"})):
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


class BrowseAnswer(unittest.TestCase):
    def test_data_on_success(self):
        self.assertEqual(mcp.browse_answer(0, json.dumps({"success": True, "data": {"title": "x"}, "error": None}), ""), {"title": "x"})

    def test_failure_keeps_the_code(self):
        with self.assertRaises(mcp.ToolError) as caught:
            mcp.browse_answer(1, json.dumps({"success": False, "data": None, "error": "Stale ref @e1", "code": "stale_ref"}), "")
        self.assertEqual((caught.exception.kind, caught.exception.code, caught.exception.message), ("browse", "stale_ref", "Stale ref @e1"))

    def test_batch_is_a_list(self):
        self.assertEqual(mcp.browse_answer(0, json.dumps([{"command": ["title"], "success": True}]), ""), {"batch": [{"command": ["title"], "success": True}]})

    def test_session_exit_without_json(self):
        with self.assertRaises(mcp.SessionGone):
            mcp.browse_answer(6, "", "ardia browse: That session has ended\n")


if __name__ == "__main__":
    unittest.main()
