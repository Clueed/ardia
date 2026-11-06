import type { BrowserState } from "./store";
import type { BrowserWindow, Profile } from "./types";

export const AGENTS_PAGE = ":agents";

export const AGENTS_LOOK: Profile = { id: AGENTS_PAGE, name: "Agents", color: "neutral", icon: null, createdAt: 0, kind: "agent" };

export const pageLook = (s: Profiles, pageId: string | null | undefined): Profile | undefined => (pageId === AGENTS_PAGE ? AGENTS_LOOK : s.profiles[pageId ?? ""]);

type Profiles = Pick<BrowserState, "profiles">;

export const isAgent = (profile: Profile | undefined): boolean => profile?.kind === "agent";

export const isAgentProfile = (s: Profiles, profileId: string | undefined): boolean => !!profileId && isAgent(s.profiles[profileId]);

export const agentProfileIds = (profiles: Record<string, Profile>): string[] =>
  Object.values(profiles)
    .filter(isAgent)
    .sort((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id))
    .map((p) => p.id);

export const showsAgentsPage = (s: Profiles, w: BrowserWindow | undefined): boolean =>
  !!w && w.kind !== "private" && (!!w.agentsPage || isAgentProfile(s, w.profileId));

export const pageIdOf = (s: Profiles, w: BrowserWindow | undefined): string | null => {
  if (!w || w.kind === "private") return null;
  return showsAgentsPage(s, w) ? AGENTS_PAGE : w.profileId;
};

export const pagerOrderOf = (profileOrder: readonly string[]): string[] => [AGENTS_PAGE, ...profileOrder];

export function ownerProfileOf(s: Pick<BrowserState, "profiles" | "settings" | "profileOrder">, w: BrowserWindow): string {
  if (w.kind === "private" || !isAgentProfile(s, w.profileId)) return w.profileId;
  const owner = w.ownerProfileId;
  if (owner && s.profiles[owner] && !isAgentProfile(s, owner)) return owner;
  return s.profiles[s.settings.defaultProfileId] && !isAgentProfile(s, s.settings.defaultProfileId) ? s.settings.defaultProfileId : (s.profileOrder[0] ?? w.profileId);
}

export function withoutAgentsPage(w: BrowserWindow): BrowserWindow {
  if (!w.agentsPage && w.ownerProfileId === undefined) return w;
  const { agentsPage: _page, ownerProfileId: _owner, ...rest } = w;
  return rest;
}
