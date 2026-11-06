import { create } from "zustand";
import { confirm } from "../../platform/dialogs";
import { showMenu } from "../../platform/menus";
import { endCliSessions } from "../../platform/gateway";
import { useBrowser } from "../browser/store";
import { isAgentProfile } from "../browser/agents";
import { renameProfile } from "./profileMenu";

export const useAgentFolders = create<{ collapsed: Record<string, true> }>()(() => ({ collapsed: {} }));

export function toggleAgentFolder(profileId: string) {
  const { collapsed } = useAgentFolders.getState();
  const { [profileId]: was, ...rest } = collapsed;
  useAgentFolders.setState({ collapsed: was ? rest : { ...rest, [profileId]: true } });
}

export function createAgentProfile(name: string): string {
  return useBrowser.getState().createProfile({ name, kind: "agent", color: "neutral" });
}

export const agentProfileNamed = (name: string): string | undefined =>
  Object.values(useBrowser.getState().profiles).find((p) => p.kind === "agent" && p.name === name)?.id;

export async function deleteAgentProfile(profileId: string, windowId?: string) {
  const profile = useBrowser.getState().profiles[profileId];
  if (!profile || !isAgentProfile(useBrowser.getState(), profileId)) return;
  const { confirmed } = await confirm({
    title: `Delete “${profile.name}”?`,
    message: "Its tabs close, agents using it are disconnected, and everything it stored (cookies, history, site data) is removed. This action cannot be undone.",
    confirmTitle: "Delete",
    destructive: true,
    windowId,
  });
  if (!confirmed || !useBrowser.getState().profiles[profileId]) return;
  await endCliSessions(profileId).catch(() => {});
  useBrowser.getState().deleteProfile(profileId);
}

export async function openAgentFolderMenu(profileId: string, windowId: string) {
  const choice = await showMenu([
    { id: "rename", title: "Rename…", symbol: "pencil" },
    { separator: true },
    { id: "delete", title: "Delete…", symbol: "trash" },
  ]);
  if (choice === "rename") return void renameProfile(profileId, windowId);
  if (choice === "delete") return void deleteAgentProfile(profileId, windowId);
}
