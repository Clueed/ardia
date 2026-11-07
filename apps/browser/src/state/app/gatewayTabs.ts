import { gatewayTabOpened, onGatewayCloseTab, onGatewayOpenTab, setGatewayShownTabs, type GatewayOpenTab } from "../../platform/gateway";
import { useBrowser, type BrowserState } from "../browser/store";
import { activeTabId } from "../browser/model";
import { isAgentProfile } from "../browser/agents";
import { mainWindowFor } from "../windows/small";
import { symbolIcon } from "../../lib/customIcon";

const quietly = (call: Promise<unknown>) => void call.catch(() => {});

export function shownTabsByProfile(s: BrowserState): Record<string, string> {
  const shown: Record<string, string> = {};
  for (const windowId of [...new Set([...s.ui.focusOrder, ...s.windowOrder])]) {
    const w = s.windows[windowId];
    if (!w || w.kind === "private" || shown[w.profileId]) continue;
    const tabId = activeTabId(s, windowId);
    if (tabId && s.tabs[tabId]?.url) shown[w.profileId] = tabId;
  }
  return shown;
}

export const AGENT_FOLDER_ICON = symbolIcon("terminal");

export const agentFolderOf = (s: Pick<BrowserState, "groups">, windowId: string, profileId: string, agentName: string) =>
  Object.values(s.groups).find(
    (g) => g.windowId === windowId && g.profileId === profileId && !g.pinned && !g.parentId && g.icon === AGENT_FOLDER_ICON && g.name === agentName,
  );

function fileIntoAgentFolder(tabId: string, agentName: string) {
  const s = useBrowser.getState();
  const tab = s.tabs[tabId];
  if (!tab || tab.pin) return;
  const folder = agentFolderOf(s, tab.windowId, tab.profileId, agentName);
  if (folder) s.addTabsToGroup(folder.id, [tabId]);
  else s.createGroup([tabId], { name: agentName, icon: AGENT_FOLDER_ICON });
}

export function openGatewayTab({ profile, agent: agentName, url, background }: Omit<GatewayOpenTab, "request">): string | null {
  const s = useBrowser.getState();
  if (!s.profiles[profile]) return null;
  const agent = isAgentProfile(s, profile);
  const windowId = mainWindowFor(s) ?? s.createWindow({ background: true });
  const tabId = useBrowser.getState().newTab(windowId, { url, profileId: profile, background: agent || background });
  if (tabId && !agent && agentName?.trim()) fileIntoAgentFolder(tabId, agentName.trim());
  return tabId || null;
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
  useBrowser.subscribe((s, prev) => {
    if (s.windows !== prev.windows || s.ui.focusOrder !== prev.ui.focusOrder || s.tabs !== prev.tabs) pushShown(gatewayOn());
  });
  return () => pushShown(gatewayOn());
}
