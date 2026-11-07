import type { BrowserState } from "../browser/store";
import type { ParkedPins, Tab, TabGroup } from "../browser/types";
import { activeTabId, isIncognitoProfile, pinKeyOf } from "../browser/model";
import { groupLabel, groupOf } from "../pins/tabGrouping";
import { focusedWindowOf } from "../windows/ui";
import { eligibleKind, shownPage, windowTabIds, type AutomationWindowKind } from "./automationWindows";

export type PinKind = "favorite" | "pinned";
export type ListedPin = { tab: string | null; window: string | null; title: string; url: string; pinned_url: string | null; kind: PinKind; folder: string | null };
export type ListedTab = { id: string; window: string; title: string; url: string; folder: string | null; active: boolean };
export type ListedProfile = { name: string; kind: "real" | "agent"; pins: ListedPin[]; tabs: ListedTab[] };
export type ListedWindow = { id: string; kind: AutomationWindowKind; focused: boolean; profile: string };
export type TabsListing = { windows: ListedWindow[]; profiles: ListedProfile[] };

type Snapshot = Pick<BrowserState, "windows" | "windowOrder" | "tabs" | "peeks" | "groups" | "profiles" | "profileOrder" | "parkedPins" | "ui">;

const pinnedGroupOf = (s: Pick<BrowserState, "groups">, tabId: string): TabGroup | undefined =>
  Object.values(s.groups).find((g) => g.pinned && g.tabIds.includes(tabId));

function pageOf(t: { url: string; title: string; customTitle?: string | null }): { url: string; title: string } {
  const page = shownPage(t);
  return { url: page.url, title: page.title || page.url };
}

const pinKindOf = (t: Pick<Tab, "pin">): PinKind => (t.pin?.as === "tile" ? "favorite" : "pinned");

function parkedPinsOf(park: ParkedPins | undefined): ListedPin[] {
  if (!park) return [];
  const folders = new Map(park.groups.map((g) => [g.id, g.name || null]));
  return park.tabs.map((t) => {
    const url = t.url || t.pinnedUrl || "";
    return {
      tab: null,
      window: null,
      ...pageOf({ url, title: t.title, customTitle: t.customTitle }),
      pinned_url: t.pinnedUrl ?? null,
      kind: t.groupId ? "pinned" : pinKindOf(t),
      folder: t.groupId ? (folders.get(t.groupId) ?? null) : null,
    };
  });
}

export function listedProfileIds(s: Pick<BrowserState, "profiles" | "profileOrder">): string[] {
  const ids = Object.keys(s.profiles).filter((id) => !isIncognitoProfile(id));
  return [...new Set([...s.profileOrder.filter((id) => ids.includes(id)), ...ids])];
}

export function matchProfile(s: Pick<BrowserState, "profiles" | "profileOrder">, wanted: string): string | null {
  return listedProfileIds(s).find((id) => id === wanted || s.profiles[id]!.name === wanted) ?? null;
}

export function automationTabs(s: Snapshot, onlyProfileId?: string): TabsListing {
  const focused = focusedWindowOf(s);
  const windowIds = s.windowOrder.filter((id) => eligibleKind(s, id));
  const byFocus = [...new Set([...s.ui.focusOrder.filter((id) => windowIds.includes(id)), ...windowIds])];
  const profileIds = listedProfileIds(s).filter((id) => !onlyProfileId || id === onlyProfileId);
  const listed = new Map<string, ListedProfile>(
    profileIds.map((id) => [id, { name: s.profiles[id]!.name, kind: s.profiles[id]!.kind === "agent" ? "agent" : "real", pins: [], tabs: [] }]),
  );
  const seenPins = new Set<string>();
  for (const windowId of byFocus) {
    const onScreen = activeTabId(s as BrowserState, windowId);
    for (const tabId of windowTabIds(s, windowId)) {
      const t = s.tabs[tabId]!;
      const profile = listed.get(t.profileId);
      if (!profile) continue;
      const page = pageOf(t);
      const pinnedFolder = t.pin ? undefined : pinnedGroupOf(s, tabId);
      if (t.pin || pinnedFolder) {
        const key = `${t.profileId}\u0001${pinKeyOf(t)}`;
        if (seenPins.has(key)) continue;
        seenPins.add(key);
        profile.pins.push({
          tab: tabId,
          window: windowId,
          ...page,
          pinned_url: t.pinnedUrl,
          kind: t.pin ? pinKindOf(t) : "pinned",
          folder: t.pin?.as === "tile" ? (t.pin.folder?.name ?? null) : pinnedFolder ? groupLabel(s, pinnedFolder) : null,
        });
        continue;
      }
      const group = groupOf(s, tabId);
      profile.tabs.push({ id: tabId, window: windowId, ...page, folder: group ? groupLabel(s, group) : null, active: tabId === onScreen });
    }
  }
  for (const [id, profile] of listed) if (!profile.pins.length) profile.pins.push(...parkedPinsOf(s.parkedPins[id]));
  const windows = windowIds.map((id): ListedWindow => ({ id, kind: eligibleKind(s, id)!, focused: id === focused, profile: s.profiles[s.windows[id]!.profileId]?.name ?? "" }));
  return { windows, profiles: [...listed.values()] };
}
