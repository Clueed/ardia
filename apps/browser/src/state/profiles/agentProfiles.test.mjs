import assert from "node:assert/strict";
import { test } from "node:test";
const { useBrowser } = await import("../browser/store.ts");
const { AGENTS_PAGE, pageIdOf, ownerProfileOf, agentProfileIds } = await import("../browser/agents.ts");
const { cliProfiles, sessionsChanged, useCliConnect } = await import("../app/cliConnect.ts");
const { PROFILE_WAKE_LIMIT, wakeProfileTabs } = await import("../tabs/recentTabWarmup.ts");
const { extensionsProfileId } = await import("../extensions/store.ts");
const { originalProfile } = await import("../windows/small.ts");
const { closeGatewayTab, openGatewayTab, shownTabsByProfile } = await import("../app/gatewayTabs.ts");

const S = () => useBrowser.getState();
const PERSONAL = { id: "default", name: "Personal", color: "plum", icon: null, createdAt: 0 };

function setup() {
  S().hydrate({ profiles: { default: PERSONAL }, profileOrder: ["default"] });
  const work = S().createProfile({ name: "Work" });
  const agent = S().createProfile({ name: "LinkedIn", kind: "agent", shareWith: "default" });
  const w = S().createWindow({ url: "https://owner.example/" });
  S().setFocusedWindow(w);
  return { work, agent, w };
}

const page = (w) => pageIdOf(S(), S().windows[w]);

test("an agent profile has its own data and stays out of the owner's profile order", () => {
  const { agent } = setup();
  assert.equal(S().profiles[agent].kind, "agent");
  assert.equal(S().profiles[agent].dataId, undefined, "never shares another profile's Chromium data");
  assert.ok(!S().profileOrder.includes(agent));
  assert.deepEqual(agentProfileIds(S().profiles), [agent]);
});

test("hydrating keeps agent profiles out of the order and the default", () => {
  const { agent } = setup();
  const profiles = S().profiles;
  S().hydrate({ profiles, profileOrder: ["default"], settings: { defaultProfileId: agent } });
  assert.ok(!S().profileOrder.includes(agent));
  assert.notEqual(S().settings.defaultProfileId, agent);
  assert.equal(S().profiles[agent].kind, "agent");
});

test("the Agents page keeps the owner's profile for new tabs and links", () => {
  const { agent, w } = setup();
  S().showAgentsPage(w);
  assert.equal(page(w), AGENTS_PAGE);
  assert.equal(S().windows[w].profileId, "default", "nothing to show yet: the owner's page stays underneath");

  const tab = S().newTab(w, { url: "https://agent.example/", profileId: agent, background: true });
  assert.equal(S().windows[w].profileId, "default", "an agent tab lands in the background");
  S().activate(tab);
  assert.equal(S().windows[w].profileId, agent, "showing it makes its profile active");
  assert.equal(page(w), AGENTS_PAGE);
  assert.equal(ownerProfileOf(S(), S().windows[w]), "default");
  assert.equal(originalProfile(S(), S().windows[w]), "default", "links from outside keep opening in the owner's profile");

  const fresh = S().newTab(w);
  assert.equal(S().tabs[fresh].profileId, "default", "⌘T opens in the owner's profile");
  assert.equal(page(w), "default", "and goes back to its page");
});

test("an agent tab arriving never moves the page the owner is on", () => {
  const { agent, work, w } = setup();
  S().switchProfile(w, work);
  S().newTab(w, { url: "https://agent.example/", profileId: agent, background: true });
  assert.equal(page(w), work);
});

test("switching back from the Agents page shows the owner's profile", () => {
  const { w } = setup();
  S().showAgentsPage(w);
  S().switchProfile(w, "default");
  assert.equal(page(w), "default");
  assert.equal(S().windows[w].agentsPage, undefined);
});

test("re-entering the Agents page shows the agent tab seen last", () => {
  const { agent, w } = setup();
  const tab = S().newTab(w, { url: "https://agent.example/", profileId: agent, background: true });
  S().activate(tab);
  S().switchProfile(w, "default");
  S().showAgentsPage(w);
  assert.equal(S().windows[w].activeTabIds[agent], tab);
  assert.equal(S().windows[w].profileId, agent);
});

test("closing the last agent tab keeps the window", () => {
  const { agent, w } = setup();
  const tab = S().newTab(w, { url: "https://agent.example/", profileId: agent, background: true });
  S().activate(tab);
  S().closeTabs([tab], { lastClosesWindow: true });
  assert.ok(S().windows[w], "the window stays");
  assert.ok(!S().tabs[tab]);
  assert.equal(S().windows[w].profileId, "default", "the owner's tab shows underneath");
  assert.equal(page(w), AGENTS_PAGE, "and the Agents page stays");
});

test("deleting an agent profile keeps the Agents page and the owner's tabs", () => {
  const { agent, w } = setup();
  const tab = S().newTab(w, { url: "https://agent.example/", profileId: agent, background: true });
  S().activate(tab);
  S().deleteProfile(agent);
  assert.ok(!S().profiles[agent]);
  assert.ok(!S().tabs[tab]);
  assert.equal(S().windows[w].profileId, "default");
  assert.equal(page(w), AGENTS_PAGE);
  assert.ok(S().orphanedProfileData.includes(agent), "its data is queued for removal");
});

test("the CLI gets every profile with its kind", () => {
  const { agent, work } = setup();
  assert.deepEqual(cliProfiles(S()), [
    { id: "default", key: "", name: "Personal", kind: "real" },
    { id: work, key: work, name: "Work", kind: "real" },
    { id: agent, key: agent, name: "LinkedIn", kind: "agent" },
  ]);
});

test("the extensions screen manages the agents' set while the Agents page shows", () => {
  const { w } = setup();
  assert.equal(extensionsProfileId(null, w), "default");
  S().showAgentsPage(w);
  assert.equal(extensionsProfileId(null, w), AGENTS_PAGE);
});

test("a gateway tab for an agent opens in the background of the last focused window", () => {
  const { agent, w } = setup();
  const tabId = openGatewayTab({ profile: agent, url: "https://agent.example/", background: false });
  assert.equal(S().tabs[tabId].profileId, agent);
  assert.equal(S().tabs[tabId].windowId, w);
  assert.equal(page(w), "default", "the owner's page doesn't move");
  assert.equal(openGatewayTab({ profile: "nobody", url: "about:blank", background: true }), null);
});

test("a late gateway tab closes only when it belongs to the asking profile", () => {
  const { agent, w } = setup();
  const owner = S().windows[w].activeTabIds.default;
  closeGatewayTab(owner, agent);
  assert.ok(S().tabs[owner], "the owner's tab stays");
  const late = openGatewayTab({ profile: agent, url: "https://agent.example/", background: true });
  closeGatewayTab(late, agent);
  assert.ok(!S().tabs[late]);
});

test("shown tabs are the focused windows' visible tabs per profile", () => {
  const { w } = setup();
  assert.deepEqual(shownTabsByProfile(S()), { default: S().windows[w].activeTabIds.default });
});

function restoredAsleep(ids) {
  const tabs = { ...S().tabs };
  ids.forEach((id, i) => (tabs[id] = { ...tabs[id], page: { kind: "idle" }, lastActiveAt: 1000 + i }));
  useBrowser.setState({ tabs });
}

test("an agent connecting wakes its profile's restored tabs, newest first, and leaves the owner's asleep", () => {
  const { agent, w } = setup();
  useCliConnect.setState({ requests: [], sessions: [] });
  const agentTabs = Array.from({ length: PROFILE_WAKE_LIMIT + 2 }, (_, i) => openGatewayTab({ profile: agent, url: `https://agent.example/${i}`, background: true }));
  const owner = S().newTab(w, { url: "https://owner.example/b", background: true });
  restoredAsleep([...agentTabs, owner]);

  sessionsChanged({ sessions: [{ id: "s1", profile: agent, agent: "claude" }] });

  const woken = agentTabs.filter((id) => S().tabs[id].page.kind !== "idle");
  assert.deepEqual(woken, agentTabs.slice(-PROFILE_WAKE_LIMIT), "the most recent ones, up to the limit");
  assert.equal(S().tabs[owner].page.kind, "idle", "the owner's tabs stay asleep");

  restoredAsleep(agentTabs);
  sessionsChanged({ sessions: [{ id: "s1", profile: agent, agent: "claude" }] });
  assert.ok(agentTabs.every((id) => S().tabs[id].page.kind === "idle"), "a session already known wakes nothing again");
});

test("a session on a real profile wakes nothing", () => {
  const { w } = setup();
  useCliConnect.setState({ requests: [], sessions: [] });
  const owner = S().newTab(w, { url: "https://owner.example/b", background: true });
  restoredAsleep([owner]);
  sessionsChanged({ sessions: [{ id: "s2", profile: "default", agent: "claude" }] });
  assert.equal(S().tabs[owner].page.kind, "idle");
  assert.deepEqual(wakeProfileTabs("nobody"), []);
});
