import type { BrowserState } from "../browser/store";
import type { TabGroup } from "../browser/types";
import { symbolIcon } from "../../lib/customIcon";

type Groups = Pick<BrowserState, "groups">;

export const AGENT_FOLDER_ICON = symbolIcon("terminal");

export const isAgentFolder = (g: TabGroup | undefined): g is TabGroup => !!g && !g.pinned && !g.parentId && g.icon === AGENT_FOLDER_ICON;

export const agentFolderOf = (s: Groups, windowId: string, profileId: string, agentName: string) =>
  Object.values(s.groups).find((g) => g.windowId === windowId && g.profileId === profileId && isAgentFolder(g) && g.name === agentName);

export const agentFolderOfTab = (s: Groups, tabId: string): TabGroup | undefined =>
  Object.values(s.groups).find((g) => isAgentFolder(g) && g.tabIds.includes(tabId));

export const sameAgentFolder = (a: TabGroup, b: TabGroup) => a.profileId === b.profileId && a.name === b.name && isAgentFolder(a) && isAgentFolder(b);

const isAgentWindowOf = (s: Pick<BrowserState, "windows">, windowId: string) => !!s.windows[windowId]?.agentSession;

export function agentWindowTabsOf(s: Pick<BrowserState, "windows" | "windowOrder" | "tabs">, profileId: string): string[] {
  return s.windowOrder
    .map((id) => s.windows[id])
    .filter((w) => !!w?.agentSession)
    .flatMap((w) => w!.tabIds.filter((id) => s.tabs[id]?.profileId === profileId && !s.tabs[id]!.pin));
}

export function lentFolderTabs(s: Pick<BrowserState, "windows" | "groups">, folder: TabGroup): string[] {
  if (!isAgentFolder(folder) || !s.windows[folder.windowId] || isAgentWindowOf(s, folder.windowId)) return [];
  return Object.values(s.groups).flatMap((g) => (isAgentWindowOf(s, g.windowId) && sameAgentFolder(g, folder) ? g.tabIds : []));
}

export const folderHasLentTabs = (s: Pick<BrowserState, "windows" | "groups">, groupId: string): boolean => {
  const g = s.groups[groupId];
  return !!g && (isAgentWindowOf(s, g.windowId) ? isAgentFolder(g) && g.tabIds.length > 0 : lentFolderTabs(s, g).length > 0);
};
