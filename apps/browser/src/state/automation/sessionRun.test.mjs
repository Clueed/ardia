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
  assert.deepEqual(ok, { command: "nextTab", arg: null, windowId: w, tabId: null, profileId: "default" });
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
  stub.emitEvent("gateway.run", { request: "r1", profile: "default", command: "nextTab", arg: null, window: null, tab: null });
  stub.emitEvent("gateway.run", { request: "r2", profile: "default", command: "setAppearance", arg: "dark", window: null, tab: null });
  stub.emitEvent("gateway.run", { request: "r3", profile: "default", command: "nextTab", arg: null, window: "nope", tab: null });
  for (let i = 0; i < 10 && stub.gatewayRunReplies.length < 3; i++) await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(stub.gatewayRunReplies.map((r) => [r.request, r.result ?? r.error.code]), [
    ["r1", { ok: true }],
    ["r2", "refused"],
    ["r3", "no_window"],
  ]);
  assert.notEqual(S().settings.appearance, "dark");
  assert.ok(w);
});

test("a tab target in the session's profile runs without focusing it; any other tab is no_window", () => {
  const { agent, work, w } = setup();
  const shown = model.activeTabId(S(), w);
  const mine = S().newTab(w, { url: "https://agent.example/1", profileId: agent, background: true });
  const ready = plan(agent, { command: "toggleMute", tab: mine });
  assert.deepEqual(ready, { command: "toggleMute", arg: null, windowId: w, tabId: mine, profileId: agent });
  assert.deepEqual(runSessionCommand(ready), { result: { ok: true } });
  assert.equal(S().tabs[mine].muted, true);
  assert.equal(model.activeTabId(S(), w), shown);
  assert.equal(code(plan(agent, { command: "toggleMute", tab: shown })), "no_window");
  assert.equal(code(plan(work, { command: "toggleMute", tab: mine })), "no_window");
  assert.equal(code(plan(agent, { command: "toggleMute", tab: "nope" })), "no_window");
  assert.equal(code(plan(agent, { command: "toggleMute", tab: 7 })), "no_window");
  assert.equal(code(plan(agent, { command: "toggleMute", tab: mine, window: "nope" })), "no_window");
  assert.equal(code(plan(agent, { command: "newTab", tab: mine })), "bad_request");
  assert.equal(code(plan(agent, { command: "nextTab", tab: mine })), "bad_request");
  assert.equal(code(plan(agent, { command: "setAppearance", tab: mine })), "refused");
  const priv = S().createWindow({ kind: "private", url: "https://secret.example/" });
  assert.equal(code(plan("default", { command: "toggleMute", tab: model.activeTabId(S(), priv) })), "no_window");
  S().closeTab(mine);
  assert.equal(code(plan(agent, { command: "toggleMute", tab: mine })), "no_window");
});

test("a tab target runs before Peek and the command panel; a Peek tab is no_window", () => {
  const { w } = setup();
  const shown = model.activeTabId(S(), w);
  const background = S().newTab(w, { url: "https://b.example/", background: true });
  const peek = S().openPeek(shown, "https://peek.example/");
  S().openPanel(w, "");
  assert.deepEqual(runSessionCommand(plan("default", { command: "closeTab", tab: background })), { result: { ok: true } });
  assert.equal(S().tabs[background], undefined);
  assert.equal(S().peeks[w]?.tabId, peek);
  assert.equal(S().windowUi[w].panel.open, true);
  assert.equal(code(plan("default", { command: "closeTab", tab: background })), "no_window");
  assert.equal(code(plan("default", { command: "closeTab", tab: peek })), "no_window");
});

test("a Little Ardia tab takes its page commands and closeTab, not tab moves", () => {
  setup();
  const little = S().createWindow({ kind: "small", url: "https://l.example/" });
  const tab = model.activeTabId(S(), little);
  assert.equal(code(plan("default", { command: "duplicateTab", tab })), "bad_request");
  assert.equal(code(plan("default", { command: "moveTabUp", tab })), "bad_request");
  assert.deepEqual(runSessionCommand(plan("default", { command: "reload", tab })), { result: { ok: true } });
  assert.deepEqual(plan("default", { command: "closeTab", tab }), { command: "closeTab", arg: null, windowId: little, tabId: tab, profileId: "default" });
});

test("a gateway run passes its tab through", async () => {
  const { agent, w } = setup();
  const mine = S().newTab(w, { url: "https://agent.example/1", profileId: agent, background: true });
  startSessionRuns();
  stub.gatewayRunReplies.length = 0;
  stub.emitEvent("gateway.run", { request: "t1", profile: agent, command: "toggleMute", arg: null, window: null, tab: mine });
  stub.emitEvent("gateway.run", { request: "t2", profile: "default", command: "toggleMute", arg: null, window: null, tab: mine });
  for (let i = 0; i < 10 && stub.gatewayRunReplies.length < 2; i++) await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(stub.gatewayRunReplies.map((r) => [r.request, r.result ?? r.error.code]), [
    ["t1", { ok: true }],
    ["t2", "no_window"],
  ]);
  assert.equal(S().tabs[mine].muted, true);
});
