import { useBrowser } from "../browser/store";
import { extensionProfile } from "./store";
import { AGENTS_PAGE, agentProfileIds } from "../browser/agents";
import { engineProfile } from "../browser/model";

export const useExtensionProfile = (windowId: string): string => useBrowser((s) => extensionProfile(s, windowId));

export const useAgentLead = (): string | null => useBrowser((s) => agentProfileIds(s.profiles)[0] ?? null);

export const useExtensionsEngineProfile = (profileId: string, agentLead: string | null): string | null =>
  useBrowser((s) => (profileId === AGENTS_PAGE ? (agentLead ? engineProfile(s, agentLead) : null) : engineProfile(s, profileId)));
