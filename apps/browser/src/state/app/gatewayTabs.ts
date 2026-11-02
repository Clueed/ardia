import { gatewayTabOpened, onGatewayOpenTab, setGatewayShownTabs, type GatewayOpenTab } from "../../platform/gateway";
import { useBrowser, type BrowserState } from "../browser/store";
import { activeTabId } from "../browser/model";
import { isAgentProfile } from "../browser/agents";
import { mainWindowFor } from "../windows/small";

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

export function openGatewayTab({ profile, url, background }: Omit<GatewayOpenTab, "request">): string | null {
  const s = useBrowser.getState();
  if (!s.profiles[profile]) return null;
  const agent = isAgentProfile(s, profile);
  const windowId = mainWindowFor(s) ?? s.createWindow({ background: true });
  const tabId = useBrowser.getState().newTab(windowId, { url, profileId: profile, background: agent || background });
  return tabId || null;
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
  useBrowser.subscribe((s, prev) => {
    if (s.windows !== prev.windows || s.ui.focusOrder !== prev.ui.focusOrder || s.tabs !== prev.tabs) pushShown(gatewayOn());
  });
  return () => pushShown(gatewayOn());
}
