import assert from "node:assert/strict";
import { test } from "node:test";
const { useBrowser } = await import("../browser/store.ts");
const model = await import("../browser/model.ts");
const { SESSION_COMMANDS, planSessionRun, runSessionCommand, startSessionRuns } = await import("./sessionRun.ts");
const { isAutomatable } = await import("./automationCommands.ts");
const stub = await import("../../test-native/index.ts");

const S = () => useBrowser.getState();
const PERSONAL = { id: "default", name: "Personal", color: "plum", icon: null, createdAt: 0 };

function setup() {
  S().hydrate({ profiles: { default: PERSONAL }, profileOrder: ["default"] });
  const work = S().createProfile({ name: "Work" });
  const agent = S().createProfile({ name: "LinkedIn", kind: "agent" });
  const w = S().createWindow({ url: "https://owner.example/" });
  S().newTab(w, { url: "https://owner2.example/" });
  S().setFocusedWindow(w);
  return { work, agent, w };
}

const plan = (profileId, params) => planSessionRun(S(), profileId, params);
const code = (result) => result.error?.code;

test("the allowlist holds only commands the socket could run", () => {
  for (const command of SESSION_COMMANDS) assert.ok(isAutomatable(command), command);
});

test("commands that reach beyond one profile are refused, unknown ones are unknown", () => {
  const { agent } = setup();
  for (const command of ["setAppearance", "newWindow", "newIncognitoWindow", "mergeAllWindows", "openSettings", "nextProfile", "closeAllTabs", "toggleSidebar", "copyUrl", "clearBrowsingData", "newProfile"]) {
    assert.equal(code(plan(agent, { command })), "refused", command);
  }
  assert.equal(code(plan(agent, { command: "quit" })), "unknown_command");
  assert.equal(code(plan(agent, {})), "bad_request");
  assert.equal(code(plan(agent, { command: "selectTab", arg: "12" })), "bad_request");
  assert.equal(code(plan("gone", { command: "reload" })), "refused");
});

test("tab commands need a window showing the session's profile", () => {
  const { agent, work, w } = setup();
  assert.equal(code(plan(agent, { command: "nextTab" })), "no_window");
  assert.equal(code(plan(agent, { command: "nextTab", window: w })), "no_window");
  assert.equal(code(plan(work, { command: "closeTab" })), "no_window");
  const ok = plan("default", { command: "nextTab" });
  assert.deepEqual(ok, { command: "nextTab", arg: null, windowId: w, profileId: "default" });
});

test("an agent's tab commands act only once its tab shows, and only on its tabs", () => {
  const { agent, w } = setup();
  const one = S().newTab(w, { url: "https://agent.example/1", profileId: agent, background: true });
  const two = S().newTab(w, { url: "https://agent.example/2", profileId: agent, background: true });
  const ownerShown = model.activeTabId(S(), w);
  S().activate(one);
  const ready = plan(agent, { command: "nextTab" });
  assert.equal(ready.windowId, w);
  assert.deepEqual(runSessionCommand(ready), { result: { ok: true } });
  assert.equal(model.activeTabId(S(), w), two);
  assert.equal(S().tabs[model.activeTabId(S(), w)].profileId, agent);
  assert.ok(S().tabs[ownerShown], "the owner's tabs stay");
});

test("newTab opens in the session's profile, in the background for an agent", () => {
  const { agent, w } = setup();
  const shown = model.activeTabId(S(), w);
  const before = Object.keys(S().tabs).length;
  assert.deepEqual(runSessionCommand(plan(agent, { command: "newTab" })), { result: { ok: true } });
  const made = Object.values(S().tabs).filter((t) => t.profileId === agent);
  assert.equal(Object.keys(S().tabs).length, before + 1);
  assert.equal(made.length, 1);
  assert.equal(model.activeTabId(S(), w), shown, "the owner's page doesn't move");
  assert.equal(S().windows[w].profileId, "default");
});

test("a gateway run answers through runReply", async () => {
  const { w } = setup();
  startSessionRuns();
  stub.gatewayRunReplies.length = 0;
  stub.emitEvent("gateway.run", { request: "r1", profile: "default", command: "nextTab", arg: null, window: null });
  stub.emitEvent("gateway.run", { request: "r2", profile: "default", command: "setAppearance", arg: "dark", window: null });
  stub.emitEvent("gateway.run", { request: "r3", profile: "default", command: "nextTab", arg: null, window: "nope" });
  for (let i = 0; i < 10 && stub.gatewayRunReplies.length < 3; i++) await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(stub.gatewayRunReplies.map((r) => [r.request, r.result ?? r.error.code]), [
    ["r1", { ok: true }],
    ["r2", "refused"],
    ["r3", "no_window"],
  ]);
  assert.notEqual(S().settings.appearance, "dark");
  assert.ok(w);
});
