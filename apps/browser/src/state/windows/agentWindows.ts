import type { BrowserState } from "../browser/store";
import type { BrowserWindow, Tab, TabGroup } from "../browser/types";
import { useBrowser } from "../browser/store";
import { activeTabId, inPinnedContainer } from "../browser/model";
import { isAgentProfile } from "../browser/agents";
import { isRegularWindow, mainWindowFor } from "./small";
import { moveTabsInto } from "./windows";
import { groupTree, regrouped } from "./groupMoves";

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

type Parkable = Pick<BrowserState, "windows" | "windowOrder" | "tabs" | "groups">;

export function withAgentWindowsParked<S extends Parkable>(s: S): S {
  const agents = Object.values(s.windows).filter(isAgentWindow);
  if (!agents.length) return s;
  const hostId = s.windowOrder.find((id) => isRegularWindow(s.windows[id]));
  const windows = { ...s.windows };
  for (const w of agents) delete windows[w.id];
  const host = hostId ? windows[hostId] : undefined;
  if (!host) return { ...s, windows };
  const moving = new Set(agents.flatMap((w) => w.tabIds));
  const activeTabIds = { ...agents.reduce<Record<string, string>>((all, w) => ({ ...all, ...w.activeTabIds }), {}), ...host.activeTabIds };
  windows[host.id] = { ...host, tabIds: [...host.tabIds, ...agents.flatMap((w) => w.tabIds)], activeTabIds };
  const tabs: Record<string, Tab> = { ...s.tabs };
  for (const id of moving) if (tabs[id]) tabs[id] = { ...tabs[id]!, windowId: host.id };
  const agentIds = new Set(agents.map((w) => w.id));
  const groups: Record<string, TabGroup> = {};
  for (const [id, g] of Object.entries(s.groups)) groups[id] = agentIds.has(g.windowId) ? { ...g, windowId: host.id } : g;
  return { ...s, windows, tabs, groups };
}

const borrowed = new Map<string, string>();

export function showAgentTab(windowId: string, tabId: string): boolean {
  const s = useBrowser.getState();
  const home = agentWindowOfTab(s, tabId);
  const w = s.windows[windowId];
  if (!home?.agentSession || !w || isAgentWindow(w) || w.kind !== "main") return false;
  borrowed.set(tabId, home.agentSession);
  s.moveTabsToWindow([tabId], windowId);
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

export function moveIntoAgentWindow(session: string, tabId: string): string | undefined {
  const s = useBrowser.getState();
  const tab = s.tabs[tabId];
  if (!tab) return undefined;
  const home = agentWindowOf(s, session);
  if (home) {
    if (tab.windowId !== home) s.moveTabsToWindow([tabId], home);
    else s.activate(tabId);
    return home;
  }
  return s.createWindow({ profileId: tab.profileId, tabIds: [tabId], agentSession: session, background: true });
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
  const host = mainWindowFor(s);
  if (host) {
    const trees = Object.values(s.groups)
      .filter((g) => g.windowId === id && !g.pinned && !g.parentId)
      .map((g) => groupTree(s.groups, g.id));
    useBrowser.setState(moveTabsInto(s, w.tabIds.filter((t) => !inPinnedContainer(s, t)), host));
    for (const tree of trees) {
      const root = tree[0]!;
      const now = useBrowser.getState();
      const into = Object.values(now.groups).find(
        (g) => g.windowId === host && g.profileId === root.profileId && !g.pinned && !g.parentId && g.name === root.name && g.icon === root.icon,
      );
      const members = root.tabIds.filter((t) => now.tabs[t]?.windowId === host);
      if (into) now.addTabsToGroup(into.id, members);
      else useBrowser.setState(regrouped(now, tree, host, root.profileId, false));
    }
  }
  useBrowser.getState().closeWindow(id);
}

export function closeEndedAgentWindows(liveSessions: ReadonlySet<string>) {
  const s = useBrowser.getState();
  for (const w of Object.values(s.windows)) if (w.agentSession && !liveSessions.has(w.agentSession)) parkAgentWindow(w.id);
}
