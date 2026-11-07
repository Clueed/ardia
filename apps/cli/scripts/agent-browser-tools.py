#!/usr/bin/env python3
"""Writes ardia_cli/agent_browser_tools.json: the MCP tools a pinned agent-browser lists, per tools profile.

  agent-browser-tools.py <agent-browser binary> [<out file>]

Asks `agent-browser mcp --tools <profile>` for tools/list (every page) for each profile, in a scratch HOME.
The out file defaults to apps/cli/ardia_cli/agent_browser_tools.json; - prints it.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROFILES = ("core", "network", "state", "debug", "tabs", "react", "mobile", "all")
OUT = Path(__file__).resolve().parents[1] / "ardia_cli" / "agent_browser_tools.json"
CONFIG = OUT.parent / "agent-browser.json"


def listed(program: str, profile: str, home: str) -> list[dict]:
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "AGENT_BROWSER_NO_VERSION_CHECK": "1"}
    child = subprocess.Popen([program, "mcp", "--tools", profile, "--config", str(CONFIG)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    try:
        def ask(request_id: int, method: str, params: dict) -> dict:
            child.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
            child.stdin.flush()
            while True:
                answer = json.loads(child.stdout.readline())
                if answer.get("id") == request_id:
                    if "error" in answer:
                        raise SystemExit(f"agent-browser-tools: {method} failed: {answer['error']}")
                    return answer["result"]

        ask(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "ardia-build", "version": "1"}})
        tools: list[dict] = []
        cursor = None
        request_id = 2
        while True:
            page = ask(request_id, "tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(page["tools"])
            cursor = page.get("nextCursor")
            request_id += 1
            if not cursor:
                return tools
    finally:
        child.stdin.close()
        child.wait(10)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help") or len(argv) > 2:
        sys.stdout.write(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 64
    program = argv[0]
    version = subprocess.run([program, "--version"], capture_output=True, text=True, check=True).stdout.split()[-1]
    with tempfile.TemporaryDirectory(prefix="agent-browser-tools-") as home:
        per_profile = {profile: listed(program, profile, home) for profile in PROFILES}
    every = per_profile["all"]
    text = json.dumps({
        "agentBrowser": version,
        "profiles": {profile: [tool["name"] for tool in tools] for profile, tools in per_profile.items()},
        "tools": every,
    }, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    target = argv[1] if len(argv) > 1 else str(OUT)
    if target == "-":
        sys.stdout.write(text)
    else:
        Path(target).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
