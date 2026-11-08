import { useBrowser } from "../browser/store";
import { groupLabel } from "../pins/tabGrouping";
import { folderHasLentTabs } from "../windows/agentFolders";

export const useGroupLabel = (groupId: string) => useBrowser((s) => (s.groups[groupId] ? groupLabel(s, s.groups[groupId]!) : ""));

export const useAgentWorkingIn = (groupId: string) => useBrowser((s) => folderHasLentTabs(s, groupId));
