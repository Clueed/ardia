import type { BrowserCommand } from "../../platform/commands";
import type { BrowserState } from "../browser/store";
import { useBrowser } from "../browser/store";
import { isIncognitoProfile } from "../browser/model";
import { isAgentProfile } from "../browser/agents";
import { NoCommandWindowError, runCommand } from "../commands/commands";
import { mainWindowFor } from "../windows/small";
import { PAGE_COMMANDS, LITTLE_ARDIA_PAGE_COMMANDS } from "../commands/commandCatalog";
import { automationDecision, isCatalogCommand, variantsOf } from "./automationCommands";
import { eligibleKind, isEligibleTab } from "./automationWindows";
import { failure, type MethodError } from "./automationMethods";
import { onGatewayRun, replyGatewayRun, type GatewayRun } from "../../platform/gateway";
import { errorText } from "../../lib/errors";

type GatewayRunBody = { result: { ok: true } } | { error: MethodError };

export const SESSION_COMMANDS: ReadonlySet<BrowserCommand> = new Set<BrowserCommand>([
  "newTab",
  "closeTab",
  "reload",
  "forceReload",
  "stop",
  "back",
  "forward",
  "nextTab",
  "previousTab",
  "selectTab",
  "selectLastTab",
  "duplicateTab",
  "moveTabUp",
  "moveTabDown",
  "toggleMute",
  "zoomIn",
  "zoomOut",
  "zoomReset",
  "findInPage",
  "findNext",
  "findPrevious",
]);

const TAB_TARGETS: ReadonlySet<BrowserCommand> = new Set<BrowserCommand>([...PAGE_COMMANDS, "closeTab", "togglePin", "moveTabUp", "moveTabDown", "duplicateTab", "bookmarkPage"]);

export type SessionRunPlan = { command: BrowserCommand; arg: string | null; windowId: string | null; tabId: string | null; profileId: string };

type Snapshot = Pick<BrowserState, "windows" | "windowOrder" | "ui" | "profiles" | "tabs" | "peeks">;

const showsProfile = (s: Snapshot, windowId: string, profileId: string) => {
  const w = s.windows[windowId];
  return !!w && w.kind === "main" && w.profileId === profileId;
};

export function planSessionRun(s: Snapshot, profileId: string, params: Record<string, unknown>): SessionRunPlan | { error: MethodError } {
  const { command, arg, window, tab } = params;
  if (typeof command !== "string" || !command) return failure("bad_request", "run needs a command id.");
  if (!isCatalogCommand(command)) return failure("unknown_command", `There's no command ${command}.`);
  if (!s.profiles[profileId] || isIncognitoProfile(profileId)) return failure("refused", "This session's profile is gone.");
  if (!SESSION_COMMANDS.has(command) || automationDecision(command) !== "run") {
    return failure("refused", `${command} reaches beyond one profile, so a session can't run it.`);
  }
  if (arg !== undefined && arg !== null) {
    const variants = variantsOf(command);
    if (typeof arg !== "string" || !variants?.includes(arg)) {
      return failure("bad_request", variants ? `${command} takes one of: ${variants.join(", ")}.` : `${command} takes no argument.`);
    }
  }
  const chosen = (arg as string | null | undefined) ?? null;
  if (tab !== undefined && tab !== null) {
    if (typeof tab !== "string" || !isEligibleTab(s, tab) || s.tabs[tab]!.profileId !== profileId) {
      return failure("no_window", `There's no tab ${String(tab)} in this session's profile.`);
    }
    if (!TAB_TARGETS.has(command)) return failure("bad_request", `${command} doesn't act on a tab, so it takes no tab.`);
    const windowId = s.tabs[tab]!.windowId;
    if (eligibleKind(s, windowId) === "little" && command !== "closeTab" && !LITTLE_ARDIA_PAGE_COMMANDS.has(command)) {
      return failure("bad_request", `${command} doesn't work on a Little Ardia tab.`);
    }
    if (window !== undefined && window !== null && window !== windowId) return failure("no_window", `Tab ${tab} isn't in window ${String(window)}.`);
    return { command, arg: chosen, windowId, tabId: tab, profileId };
  }
  if (window !== undefined && window !== null) {
    if (typeof window !== "string" || !s.windows[window]) return failure("no_window", `There's no window ${String(window)}.`);
    if (command === "newTab" ? s.windows[window]!.kind !== "main" : !showsProfile(s, window, profileId)) {
      return failure("no_window", `Window ${window} isn't showing this session's profile.`);
    }
    return { command, arg: chosen, windowId: window, tabId: null, profileId };
  }
  if (command === "newTab") return { command, arg: chosen, windowId: mainWindowFor(s as BrowserState) ?? null, tabId: null, profileId };
  const shown = [...new Set([...s.ui.focusOrder, ...s.windowOrder])].find((id) => showsProfile(s, id, profileId));
  if (!shown) return failure("no_window", "No window is showing this session's profile.");
  return { command, arg: chosen, windowId: shown, tabId: null, profileId };
}

export function runSessionCommand(plan: SessionRunPlan): GatewayRunBody {
  const s = useBrowser.getState();
  if (plan.command === "newTab") {
    const agent = isAgentProfile(s, plan.profileId);
    const windowId = plan.windowId ?? s.createWindow({ background: true });
    const background = agent || !showsProfile(s, windowId, plan.profileId);
    useBrowser.getState().newTab(windowId, { profileId: plan.profileId, background });
    return { result: { ok: true } };
  }
  try {
    runCommand({ command: plan.command, arg: plan.arg, windowId: plan.windowId }, { strictWindow: true, tabId: plan.tabId });
  } catch (error) {
    if (error instanceof NoCommandWindowError) return failure("no_window", error.message);
    throw error;
  }
  return { result: { ok: true } };
}

function answer(run: GatewayRun): GatewayRunBody {
  try {
    const plan = planSessionRun(useBrowser.getState(), run.profile, { command: run.command, arg: run.arg, window: run.window, tab: run.tab });
    return "error" in plan ? plan : runSessionCommand(plan);
  } catch (error) {
    return failure("failed", errorText(error));
  }
}

let started = false;

export function startSessionRuns() {
  if (started) return;
  started = true;
  onGatewayRun((run) => void replyGatewayRun({ request: run.request, ...answer(run) }).catch(() => {}));
}
