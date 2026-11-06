import type { SystemState } from "../../platform/performance";
import { useBrowser } from "../browser/store";
import { isInternalTab } from "../pages/urls";
import { holderOf } from "../pins/pinShare";
import { isLazy, restoredLazily, wokenPage } from "./pageSession";
import { shownTabIds } from "./shownTabs";

const store = () => useBrowser.getState();

export function reloadRecentTabs(sys: SystemState) {
  const gb = sys.physicalMemory / 2 ** 30;
  const busy = sys.onBattery || sys.lowPowerMode || sys.memoryPressure !== "normal";
  const count = busy ? 0 : gb >= 32 ? 4 : gb >= 16 ? 3 : gb >= 8 ? 1 : 0;
  const s = store();
  const shown = shownTabIds(s);
  const since = Date.now() - 24 * 60 * 60_000;
  const ids = Object.values(s.tabs)
    .filter((t) => restoredLazily(t) && !shown.has(t.id) && !isInternalTab(t) && t.lastActiveAt >= since)
    .filter((t) => s.windows[t.windowId]?.profileId === t.profileId)
    .sort((a, b) => b.lastActiveAt - a.lastActiveAt)
    .slice(0, count)
    .map((t) => t.id);
  ids.forEach((id, i) =>
    setTimeout(() => {
      const now = store();
      const t = now.tabs[id];
      if (t && restoredLazily(t) && !holderOf(now, id)) now.updateTab(id, { page: wokenPage(t) });
    }, 2000 * (i + 1)),
  );
  return ids;
}

export const PROFILE_WAKE_LIMIT = 8;

export function wakeProfileTabs(profileId: string, limit = PROFILE_WAKE_LIMIT) {
  const s = store();
  const ids = Object.values(s.tabs)
    .filter((t) => t.profileId === profileId && isLazy(t) && !isInternalTab(t) && !holderOf(s, t.id) && s.windows[t.windowId]?.kind !== "private")
    .sort((a, b) => b.lastActiveAt - a.lastActiveAt)
    .slice(0, limit)
    .map((t) => t.id);
  for (const id of ids) s.updateTab(id, { page: wokenPage(s.tabs[id]!) });
  return ids;
}
