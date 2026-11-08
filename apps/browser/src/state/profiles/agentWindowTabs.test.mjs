import assert from "node:assert/strict";
import { test } from "node:test";

const setTimeoutHoldingExit = globalThis.setTimeout;
globalThis.setTimeout = (callback, ms, ...args) => {
  const timer = setTimeoutHoldingExit(callback, ms, ...args);
  return ms >= 1_000 ? timer.unref() : timer;
};
const { useBrowser } = await import("../browser/store.ts");
const { activateGatewayTab, agentSessionsChanged, openGatewayTab } = await import("../app/gatewayTabs.ts");
const { AGENT_FOLDER_ICON } = await import("../windows/agentFolders.ts");
const { returnBorrowed, returnBorrowedFrom, showAgentTab, withAgentWindowsParked } = await import("../windows/agentWindows.ts");
const { groupEntries, sidebarEntries } = await import("../sidebar/entries.ts");
const { entryKey, parseEntry } = await import("../sidebar/entryKey.ts");
const { clickTab } = await import("../sidebar/actions.ts");
const { flushPersistence, loadSession, startPersistence } = await import("../session/persist.ts");
const { abandonedNewTabs, cleanUpCandidates } = await import("../pins/tabCleanup.ts");

const S = () => useBrowser.getState();
const PERSONAL = { id: "default", name: "Personal", color: "plum", icon: null, createdAt: 0 };
const LIVE = new Set(["s1"]);

function setup({ share = false, windows = 1 } = {}) {
  S().hydrate({ profiles: { default: PERSONAL }, profileOrder: ["default"] });
  const agent = S().createProfile({ name: "LinkedIn", kind: "agent", shareWith: "default" });
  if (share) S().updateSettings({ shareTabsAcrossWindows: true });
  const ws = Array.from({ length: windows }, (_, i) => S().createWindow({ url: `https://owner${i}.example/` }));
  S().setFocusedWindow(ws[0]);
  agentSessionsChanged(["s1"]);
  return { agent, w: ws[0], ws };
}

const open = (url, session = "s1", profile = "default") => openGatewayTab({ session, profile, agent: "Claude", url, background: true });
const claudeIn = (windowId) => Object.values(S().groups).filter((g) => g.windowId === windowId && g.name === "Claude" && g.icon === AGENT_FOLDER_ICON);
const folderIn = (windowId) => {
  const found = claudeIn(windowId);
  assert.ok(found.length <= 1, "one Claude folder per window");
  return found[0];
};
const agentWindow = (session = "s1") => Object.values(S().windows).find((w) => w.agentSession === session)?.id;
const listedIn = (windowId, tabId) => {
  const rows = (entry) => (parseEntry(entry).kind === "group" ? groupEntries(S(), parseEntry(entry).id).flatMap(rows) : [entry]);
  return sidebarEntries(S(), windowId, "default").list.flatMap(rows).includes(entryKey("tab", tabId));
};
const urlListedIn = (windowId, url) => {
  const rows = (entry) => (parseEntry(entry).kind === "group" ? groupEntries(S(), parseEntry(entry).id).flatMap(rows) : [entry]);
  return sidebarEntries(S(), windowId, "default")
    .list.flatMap(rows)
    .some((e) => S().tabs[parseEntry(e).id]?.url === url);
};
const ownerShows = (windowId) => S().windows[windowId].activeTabIds.default;

for (const share of [false, true]) {
  const mode = share ? "with shared tabs" : "without shared tabs";

  test(`an agent's live tab shows in the owner's sidebar, in the agent's folder, in every window (${mode})`, () => {
    const { ws } = setup({ share, windows: 2 });
    const tab = open("https://agent.example/a");
    const home = agentWindow();
    assert.equal(S().tabs[tab].windowId, home, "it lives in the agent window");
    for (const w of ws) {
      assert.ok(listedIn(w, tab), `listed in ${w}`);
      assert.ok(!S().windows[w].tabIds.includes(tab), "without a record in the owner's window");
    }
    const folderEntry = entryKey("group", folderIn(home).id);
    for (const w of ws) assert.ok(sidebarEntries(S(), w, "default").list.includes(folderEntry), "shown as the agent's folder");
    agentSessionsChanged([]);
  });

  test(`the agent's live tabs join an owner folder of the same agent instead of a second folder (${mode})`, () => {
    const { w, ws } = setup({ share, windows: 2 });
    const parked = open("https://agent.example/old");
    agentSessionsChanged([]);
    const folder = folderIn(w);
    assert.deepEqual(folder.tabIds, [parked]);
    agentSessionsChanged(["s1"]);
    const tab = open("https://agent.example/new");
    const liveFolder = entryKey("group", folderIn(agentWindow()).id);
    for (const x of ws) {
      const own = folderIn(x);
      assert.ok(listedIn(x, tab), `${x} lists the live tab`);
      if (!own) {
        assert.ok(!share && x !== w, "only a window that never had the folder shows the agent's own");
        assert.ok(sidebarEntries(S(), x, "default").list.includes(liveFolder));
        continue;
      }
      assert.ok(groupEntries(S(), own.id).includes(entryKey("tab", tab)), "the live tab is listed inside it");
      assert.ok(!sidebarEntries(S(), x, "default").list.includes(liveFolder), "no second folder");
    }
    agentSessionsChanged([]);
  });

  test(`a borrowed tab stays in the agent's folder while shown, after it goes back and after the session (${mode})`, () => {
    const { w, ws } = setup({ share, windows: 2 });
    const ownerTab = ownerShows(w);
    const tab = open("https://agent.example/a");
    const other = open("https://agent.example/b");
    assert.ok(showAgentTab(w, tab));
    assert.equal(S().tabs[tab].windowId, w);
    assert.ok(folderIn(w)?.tabIds.includes(tab), "borrowed into the owner's Claude folder");
    assert.ok(groupEntries(S(), folderIn(w).id).includes(entryKey("tab", other)), "next to the agent's other live tab");
    for (const x of share ? ws : [w]) assert.ok(urlListedIn(x, "https://agent.example/a") && urlListedIn(x, "https://agent.example/b"));
    assert.equal(activateGatewayTab({ session: "s1", profile: "default", agent: "Claude", tabId: tab }), null, "the agent still reaches it");

    S().activate(ownerTab);
    returnBorrowed(LIVE);
    assert.equal(S().tabs[tab].windowId, agentWindow());
    assert.ok(folderIn(agentWindow())?.tabIds.includes(tab), "back in the agent window's Claude folder");
    for (const x of ws) assert.ok(listedIn(x, tab), "still listed in the owner's sidebar");

    agentSessionsChanged([]);
    assert.equal(agentWindow(), undefined);
    assert.deepEqual(new Set(folderIn(w).tabIds), new Set([tab, other]), "parked together in the Claude folder");
    for (const x of share ? ws : [w]) assert.ok(urlListedIn(x, "https://agent.example/a") && urlListedIn(x, "https://agent.example/b"));
  });

  test(`a tab borrowed when the session ends stays in the owner's Claude folder (${mode})`, () => {
    const { w } = setup({ share, windows: 2 });
    const tab = open("https://agent.example/a");
    const other = open("https://agent.example/b");
    clickTab(w, tab);
    assert.equal(ownerShows(w), tab, "clicking the row shows it");
    agentSessionsChanged([]);
    assert.deepEqual(new Set(folderIn(w).tabIds), new Set([tab, other]));
    assert.equal(claudeIn(w).length, 1);
  });

  test(`a session ending with no owner window open parks its tabs in a new window (${mode})`, () => {
    const { w, agent } = setup({ share });
    const tab = open("https://agent.example/a");
    agentSessionsChanged(["s1", "s2"]);
    const own = openGatewayTab({ session: "s2", profile: agent, url: "https://agent.example/own", background: true });
    S().closeWindow(w);
    assert.equal(Object.values(S().windows).filter((x) => !x.agentSession).length, 0);
    agentSessionsChanged([]);
    assert.ok(S().tabs[tab], "the owner-profile tab is still open");
    assert.ok(S().tabs[own], "the agent profile's tab is still open");
    const host = S().tabs[tab].windowId;
    assert.equal(S().windows[host].agentSession, undefined, "in a regular window");
    assert.ok(folderIn(host)?.tabIds.includes(tab), "in the Claude folder");
    assert.equal(S().windows[S().tabs[own].windowId].agentSession, undefined);
    assert.ok(listedIn(host, tab));
  });
}

test("a native close of the owner's window sends a borrowed tab home instead of closing it", () => {
  const { w } = setup({ windows: 2 });
  const tab = open("https://agent.example/a");
  showAgentTab(w, tab);
  returnBorrowedFrom(w);
  S().closeWindow(w);
  assert.ok(S().tabs[tab]);
  assert.equal(S().tabs[tab].windowId, agentWindow());
  assert.ok(folderIn(agentWindow()).tabIds.includes(tab));
  agentSessionsChanged([]);
});

test("saving with no owner window keeps the agent's tabs in a regular window on relaunch", () => {
  const stop = startPersistence();
  const { w } = setup();
  const tab = open("https://agent.example/a");
  S().closeWindow(w);
  const parked = withAgentWindowsParked(S());
  const host = Object.values(parked.windows).find((x) => x.tabIds.includes(tab));
  assert.ok(host, "the tab has a window in the saved state");
  assert.equal(host.agentSession, undefined);
  assert.equal(host.frame, null, "not at the off-screen spot");
  assert.ok(parked.windowOrder.includes(host.id));

  flushPersistence();
  stop();
  S().hydrate(loadSession());
  const restored = Object.values(S().tabs).find((t) => t.url === "https://agent.example/a");
  assert.ok(restored, "the tab is back after relaunch");
  const back = S().windows[restored.windowId];
  assert.equal(back.kind, "main");
  assert.equal(back.agentSession, undefined);
  assert.ok(folderIn(back.id)?.tabIds.includes(restored.id), "in the Claude folder");
  agentSessionsChanged([]);
});

test("saving mid-borrow keeps one Claude folder with all the agent's tabs", () => {
  const { w } = setup();
  const tab = open("https://agent.example/a");
  const other = open("https://agent.example/b");
  showAgentTab(w, tab);
  const parked = withAgentWindowsParked(S());
  const folders = Object.values(parked.groups).filter((g) => g.name === "Claude");
  assert.equal(folders.length, 1);
  assert.deepEqual(new Set(folders[0].tabIds), new Set([tab, other]));
  assert.equal(parked.tabs[other].windowId, w);
  const order = parked.windows[w].tabIds;
  const at = folders[0].tabIds.map((id) => order.indexOf(id)).sort((a, b) => a - b);
  assert.equal(at[1] - at[0], 1, "the folder's tabs sit together");
  agentSessionsChanged([]);
});

test("tab clean-up never closes an agent window's tabs or a parked agent's tabs", () => {
  const { w } = setup();
  const blank = open("");
  const tab = open("https://agent.example/a");
  open("https://agent.example/a");
  const home = agentWindow();
  assert.deepEqual(abandonedNewTabs(S(), home), []);
  assert.deepEqual(cleanUpCandidates(S(), home, 0, Date.now() + 1e9), []);
  S().closeAbandonedNewTabs();
  assert.ok(S().tabs[blank]);
  agentSessionsChanged([]);
  assert.equal(S().tabs[tab].windowId, w);
  assert.deepEqual(cleanUpCandidates(S(), w, 0, Date.now() + 1e9).filter((id) => folderIn(w).tabIds.includes(id)), []);
  assert.deepEqual(abandonedNewTabs(S(), w).filter((id) => folderIn(w).tabIds.includes(id)), []);
});
