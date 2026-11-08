import {
  gatewayTabOpened,
  onGatewayActivateTab,
  onGatewayCloseTab,
  onGatewayOpenTab,
  replyGatewayActivate,
  setGatewayShownTabs,
  type GatewayActivateTab,
  type GatewayOpenTab,
} from "../../platform/gateway";
import { useBrowser, type BrowserState } from "../browser/store";
import { activeTabId } from "../browser/model";
import { isAgentProfile } from "../browser/agents";
import { isRegularWindow, mainWindowFor } from "../windows/small";
import { agentWindowOf, borrowedBy, closeEndedAgentWindows, fileIntoAgentFolder, isAgentWindow, moveIntoAgentWindow, returnBorrowed, shownByOwner } from "../windows/agentWindows";
import { agentFolderOf } from "../windows/agentFolders";

const quietly = (call: Promise<unknown>) => void call.catch(() => {});

export function shownTabsByProfile(s: BrowserState): Record<string, string> {
  const shown: Record<string, string> = {};
  const agentLast = [...new Set([...s.ui.focusOrder, ...s.windowOrder])].sort((a, b) => Number(isAgentWindow(s.windows[a])) - Number(isAgentWindow(s.windows[b])));
  for (const windowId of agentLast) {
    const w = s.windows[windowId];
    if (!w || w.kind === "private" || shown[w.profileId]) continue;
    const tabId = activeTabId(s, windowId);
    if (tabId && s.tabs[tabId]?.url) shown[w.profileId] = tabId;
  }
  return shown;
}

function openAgentWindow(session: string, profile: string, url: string): string | undefined {
  const windowId = useBrowser.getState().createWindow({ profileId: profile, url, agentSession: session, background: true });
  return activeTabId(useBrowser.getState(), windowId, profile);
}

export function openGatewayTab({ session, profile, agent: agentName, url, background }: Omit<GatewayOpenTab, "request">): string | null {
  const s = useBrowser.getState();
  if (!s.profiles[profile]) return null;
  const agent = isAgentProfile(s, profile);
  if (session) {
    const home = agentWindowOf(s, session);
    const tabId = home ? s.newTab(home, { url, profileId: profile }) : openAgentWindow(session, profile, url);
    if (tabId && !agent && agentName?.trim()) fileIntoAgentFolder(tabId, agentName.trim());
    return tabId || null;
  }
  const windowId = mainWindowFor(s) ?? s.createWindow({ background: true });
  const tabId = useBrowser.getState().newTab(windowId, { url, profileId: profile, background: agent || background });
  if (tabId && !agent && agentName?.trim()) fileIntoAgentFolder(tabId, agentName.trim());
  return tabId || null;
}

export const OWNER_TAB = "that's the owner's tab; open your own";

const inAgentFolder = (s: BrowserState, tabId: string, agentName: string | undefined) => {
  const tab = s.tabs[tabId];
  const name = agentName?.trim();
  if (!tab || !name || !isRegularWindow(s.windows[tab.windowId])) return false;
  return !!agentFolderOf(s, tab.windowId, tab.profileId, name)?.tabIds.includes(tabId);
};

export function activateGatewayTab({ session, profile, agent, tabId }: Omit<GatewayActivateTab, "request">): string | null {
  const s = useBrowser.getState();
  const tab = s.tabs[tabId];
  if (!tab || tab.profileId !== profile) return OWNER_TAB;
  const home = agentWindowOf(s, session);
  if (home && tab.windowId === home) {
    s.activate(tabId);
    return null;
  }
  if (borrowedBy(tabId) === session) return null;
  const ours = isAgentProfile(s, profile) || inAgentFolder(s, tabId, agent);
  if (!ours) return OWNER_TAB;
  if (!shownByOwner(s, tabId)) moveIntoAgentWindow(session, tabId);
  return null;
}

let liveSessions: ReadonlySet<string> = new Set();
let returning = false;

export function agentSessionsChanged(ids: string[]) {
  liveSessions = new Set(ids);
  closeEndedAgentWindows(liveSessions);
  returnBorrowed(liveSessions);
}

function returnLater() {
  if (returning) return;
  returning = true;
  queueMicrotask(() => {
    returning = false;
    returnBorrowed(liveSessions);
  });
}

export function closeGatewayTab(tabId: string, profile: string) {
  if (useBrowser.getState().tabs[tabId]?.profileId === profile) useBrowser.getState().closeTabs([tabId]);
}

let sentShown = "";

function pushShown(on: boolean) {
  if (!on) {
    sentShown = "";
    return;
  }
  const shown = shownTabsByProfile(useBrowser.getState());
  const signature = JSON.stringify(shown);
  if (signature === sentShown) return;
  sentShown = signature;
  quietly(setGatewayShownTabs(shown));
}

export function startGatewayTabs(gatewayOn: () => boolean) {
  onGatewayOpenTab(({ request, ...open }) => quietly(gatewayTabOpened(request, openGatewayTab(open))));
  onGatewayCloseTab(({ tabId, profile }) => closeGatewayTab(tabId, profile));
  onGatewayActivateTab(({ request, ...activate }) => quietly(replyGatewayActivate(request, activateGatewayTab(activate))));
  useBrowser.subscribe((s, prev) => {
    if (s.windows !== prev.windows || s.ui.focusOrder !== prev.ui.focusOrder || s.tabs !== prev.tabs) pushShown(gatewayOn());
    if (s.windows !== prev.windows || s.tabs !== prev.tabs) returnLater();
  });
  return () => pushShown(gatewayOn());
}
