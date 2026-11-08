import type { BrowserState } from "../browser/store";
import type { BrowserWindow, Tab, TabGroup } from "../browser/types";
import { useBrowser } from "../browser/store";
import { activeTabId, inPinnedContainer } from "../browser/model";
import { isAgentProfile, ownerProfileOf } from "../browser/agents";
import { isRegularWindow, mainWindowFor } from "./small";
import { moveTabsInto } from "./windows";
import { groupTree, regrouped } from "./groupMoves";
import { orderSections } from "../groups/groups";
import { AGENT_FOLDER_ICON, agentFolderOf, agentFolderOfTab, isAgentFolder, sameAgentFolder } from "./agentFolders";

type Windows = Pick<BrowserState, "windows">;
type Placed = Pick<BrowserState, "windows" | "tabs">;

export const isAgentWindow = (w: BrowserWindow | undefined): boolean => !!w?.agentSession;

export const agentWindowOf = (s: Windows, session: string): string | undefined =>
  Object.values(s.windows).find((w) => w.agentSession === session)?.id;

export const agentWindowOfProfile = (s: Windows, profileId: string): string | undefined =>
  Object.values(s.windows).find((w) => !!w.agentSession && w.profileId === profileId)?.id;

export const inAgentWindow = (s: Placed, tabId: string): boolean => isAgentWindow(s.windows[s.tabs[tabId]?.windowId ?? ""]);

export const agentWindowOfTab = (s: Placed, tabId: string): BrowserWindow | undefined => {
  const w = s.windows[s.tabs[tabId]?.windowId ?? ""];
  return isAgentWindow(w) ? w : undefined;
};

export function agentWindowTabIds(s: BrowserState, profileId: string): string[] {
  return Object.values(s.windows)
    .filter(isAgentWindow)
    .flatMap((w) => w.tabIds.filter((id) => s.tabs[id]?.profileId === profileId));
}

const shownIn = (s: BrowserState, w: BrowserWindow, tabId: string) => activeTabId(s, w.id) === tabId;

export function shownByOwner(s: BrowserState, tabId: string): boolean {
  const w = s.windows[s.tabs[tabId]?.windowId ?? ""];
  return !!w && !isAgentWindow(w) && shownIn(s, w, tabId);
}

type Parkable = Pick<BrowserState, "windows" | "windowOrder" | "tabs" | "groups" | "profiles" | "settings" | "profileOrder">;

function asRegularWindow(s: Parkable, w: BrowserWindow): BrowserWindow {
  const { agentSession: _, ...rest } = w;
  const regular = { ...rest, sidebarOpen: true, frame: null };
  return isAgentProfile(s, w.profileId) ? { ...regular, agentsPage: true, ownerProfileId: ownerProfileOf(s, w) } : regular;
}

export function withAgentWindowsParked<S extends Parkable>(s: S): S {
  const agents = Object.values(s.windows).filter(isAgentWindow);
  if (!agents.length) return s;
  const hostId = s.windowOrder.find((id) => isRegularWindow(s.windows[id]));
  const windows = { ...s.windows };
  for (const w of agents) delete windows[w.id];
  const host = hostId ? windows[hostId]! : asRegularWindow(s, agents[0]!);
  const guests = agents.filter((w) => w.id !== host.id);
  const moving = guests.flatMap((w) => w.tabIds);
  const tabs: Record<string, Tab> = { ...s.tabs };
  for (const id of moving) if (tabs[id]) tabs[id] = { ...tabs[id]!, windowId: host.id };
  const agentIds = new Set(agents.map((w) => w.id));
  const groups: Record<string, TabGroup> = {};
  for (const [id, g] of Object.entries(s.groups)) if (!agentIds.has(g.windowId)) groups[id] = g;
  for (const [id, g] of Object.entries(s.groups)) {
    if (!agentIds.has(g.windowId)) continue;
    const into = isAgentFolder(g) ? Object.values(groups).find((x) => x.windowId === host.id && sameAgentFolder(x, g)) : undefined;
    if (into) groups[into.id] = { ...into, tabIds: [...into.tabIds, ...g.tabIds.filter((t) => !into.tabIds.includes(t))] };
    else groups[id] = { ...g, windowId: host.id };
  }
  const activeTabIds = { ...guests.reduce<Record<string, string>>((all, w) => ({ ...all, ...w.activeTabIds }), {}), ...host.activeTabIds };
  windows[host.id] = { ...host, tabIds: orderSections([...host.tabIds, ...moving], tabs, groups), activeTabIds };
  return { ...s, windows, tabs, groups };
}

export function fileIntoAgentFolder(tabId: string, agentName: string) {
  const s = useBrowser.getState();
  const tab = s.tabs[tabId];
  if (!tab || tab.pin) return;
  const folder = agentFolderOf(s, tab.windowId, tab.profileId, agentName);
  if (folder) s.addTabsToGroup(folder.id, [tabId]);
  else s.createGroup([tabId], { name: agentName, icon: AGENT_FOLDER_ICON });
}

function moveKeepingFolder(tabId: string, windowId: string) {
  const folder = agentFolderOfTab(useBrowser.getState(), tabId)?.name;
  useBrowser.getState().moveTabsToWindow([tabId], windowId);
  if (folder !== undefined) fileIntoAgentFolder(tabId, folder);
}

const borrowed = new Map<string, string>();

export function showAgentTab(windowId: string, tabId: string): boolean {
  const s = useBrowser.getState();
  const home = agentWindowOfTab(s, tabId);
  const w = s.windows[windowId];
  if (!home?.agentSession || !w || isAgentWindow(w) || w.kind !== "main") return false;
  borrowed.set(tabId, home.agentSession);
  moveKeepingFolder(tabId, windowId);
  return true;
}

export const borrowedTabIds = (): ReadonlySet<string> => new Set(borrowed.keys());

export const borrowedBy = (tabId: string): string | undefined => borrowed.get(tabId);

export function returnBorrowed(liveSessions: ReadonlySet<string>) {
  const s = useBrowser.getState();
  for (const [tabId, session] of [...borrowed]) {
    const tab = s.tabs[tabId];
    if (!tab || !liveSessions.has(session) || isAgentWindow(s.windows[tab.windowId])) {
      borrowed.delete(tabId);
      continue;
    }
    if (shownByOwner(s, tabId)) continue;
    borrowed.delete(tabId);
    moveIntoAgentWindow(session, tabId);
  }
}

export function returnBorrowedFrom(windowId: string) {
  const s = useBrowser.getState();
  for (const [tabId, session] of [...borrowed]) {
    if (s.tabs[tabId]?.windowId !== windowId) continue;
    borrowed.delete(tabId);
    moveIntoAgentWindow(session, tabId);
  }
}

export function moveIntoAgentWindow(session: string, tabId: string): string | undefined {
  const s = useBrowser.getState();
  const tab = s.tabs[tabId];
  if (!tab) return undefined;
  const home = agentWindowOf(s, session);
  if (home) {
    if (tab.windowId !== home) moveKeepingFolder(tabId, home);
    else s.activate(tabId);
    return home;
  }
  const folder = agentFolderOfTab(s, tabId)?.name;
  const id = s.createWindow({ profileId: tab.profileId, tabIds: [tabId], agentSession: session, background: true });
  if (folder !== undefined) fileIntoAgentFolder(tabId, folder);
  return id;
}

export function wakeIntoAgentWindow(session: string, profileId: string): string | undefined {
  const s = useBrowser.getState();
  if (!isAgentProfile(s, profileId) || agentWindowOf(s, session)) return undefined;
  const tabIds = Object.values(s.tabs)
    .filter((t) => t.profileId === profileId && !t.pin && !!t.url && s.windows[t.windowId]?.kind === "main" && !isAgentWindow(s.windows[t.windowId]) && !shownByOwner(s, t.id))
    .sort((a, b) => b.lastActiveAt - a.lastActiveAt)
    .map((t) => t.id);
  if (!tabIds.length) return undefined;
  return s.createWindow({ profileId, tabIds, agentSession: session, background: true });
}

export function parkAgentWindow(id: string) {
  const s = useBrowser.getState();
  const w = s.windows[id];
  if (!w?.agentSession) return;
  const parking = w.tabIds.filter((t) => !inPinnedContainer(s, t));
  const trees = Object.values(s.groups)
    .filter((g) => g.windowId === id && !g.pinned && !g.parentId)
    .map((g) => groupTree(s.groups, g.id));
  let host = mainWindowFor(s);
  if (host) useBrowser.setState(moveTabsInto(s, parking, host));
  else if (parking.length) host = s.createWindow({ profileId: isAgentProfile(s, w.profileId) ? undefined : w.profileId, tabIds: parking, background: true });
  for (const tree of host ? trees : []) {
    const root = tree[0]!;
    const now = useBrowser.getState();
    const into = Object.values(now.groups).find(
      (g) => g.windowId === host && g.profileId === root.profileId && !g.pinned && !g.parentId && g.name === root.name && g.icon === root.icon,
    );
    const members = root.tabIds.filter((t) => now.tabs[t]?.windowId === host);
    if (into) now.addTabsToGroup(into.id, members);
    else useBrowser.setState(regrouped(now, tree, host!, root.profileId, false));
  }
  useBrowser.getState().closeWindow(id);
}

export function closeEndedAgentWindows(liveSessions: ReadonlySet<string>) {
  const s = useBrowser.getState();
  for (const w of Object.values(s.windows)) if (w.agentSession && !liveSessions.has(w.agentSession)) parkAgentWindow(w.id);
}
