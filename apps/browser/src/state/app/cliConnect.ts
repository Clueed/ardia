import { AppState } from "react-native";
import { create } from "zustand";
import {
  onCliConnectCancel,
  onCliConnectRequest,
  onCliRename,
  onGatewayActivity,
  onCliSessions,
  replyCliConnect,
  setGatewayProfiles,
  startGateway,
  stopGateway,
  type CliConnectRequest,
  type CliSession,
  type GatewayProfile,
} from "../../platform/gateway";
import { backgroundInstance } from "../../platform/app";
import { notificationPermission, onNotificationResponse, postNotification, removeNotifications, requestNotificationPermission } from "../../platform/notifications";
import { useBrowser, type BrowserState } from "../browser/store";
import { agentProfileIds, isAgentProfile } from "../browser/agents";
import { engineProfile } from "../browser/model";
import { createAgentProfile } from "../profiles/agents";
import { seedAgentExtensions } from "../extensions/agentExtensions";
import { noteGatewayActive, useCli } from "./cliControl";
import { startGatewayTabs } from "./gatewayTabs";
import { startSessionRuns } from "../automation/sessionRun";
import { wakeProfileTabs } from "../tabs/recentTabWarmup";

export type PendingConnect = { id: string; agent: string; profileId: string; profileName: string };

export const useCliConnect = create<{ requests: PendingConnect[]; sessions: CliSession[] }>()(() => ({ requests: [], sessions: [] }));

const NOTIFICATION = "cli-connect:";
const quietly = (call: Promise<unknown>) => void call.catch(() => {});

export function cliProfiles(s: Pick<BrowserState, "profiles" | "profileOrder">): GatewayProfile[] {
  const entry = (id: string, kind: GatewayProfile["kind"]): GatewayProfile => ({ id, key: engineProfile(s, id), name: s.profiles[id]!.name, kind });
  return [...s.profileOrder.filter((id) => s.profiles[id]).map((id) => entry(id, "real")), ...agentProfileIds(s.profiles).map((id) => entry(id, "agent"))];
}

let gatewayOn = false;
const controlOn = () => gatewayOn;

let sentProfiles: string | null = null;

function pushProfiles(force = false): Promise<unknown> {
  if (!controlOn()) {
    sentProfiles = null;
    return Promise.resolve();
  }
  const profiles = cliProfiles(useBrowser.getState());
  const signature = JSON.stringify(profiles);
  if (!force && signature === sentProfiles) return Promise.resolve();
  sentProfiles = signature;
  return setGatewayProfiles(profiles).catch(() => {
    sentProfiles = null;
  });
}

function profileNamed(name: string | undefined): string | undefined {
  const s = useBrowser.getState();
  if (name === undefined) return undefined;
  if (s.profiles[name]) return name;
  const ids = [...s.profileOrder.filter((id) => s.profiles[id]), ...agentProfileIds(s.profiles)];
  const folded = name.toLowerCase();
  return ids.find((id) => s.profiles[id]!.name === name) ?? ids.find((id) => s.profiles[id]!.name.toLowerCase() === folded);
}

function nameTaken(name: string) {
  return Object.values(useBrowser.getState().profiles).some((p) => p.name.trim().toLowerCase() === name.toLowerCase());
}

async function connectNew(request: string, name: string) {
  const trimmed = name.trim();
  if (!trimmed || nameTaken(trimmed)) return quietly(replyCliConnect({ request, allow: false }));
  const profileId = createAgentProfile(trimmed);
  seedAgentExtensions(profileId);
  await pushProfiles(true);
  const profile = useBrowser.getState().profiles[profileId];
  quietly(replyCliConnect(profile ? { request, allow: true, profile: profileId } : { request, allow: false }));
}

function received(request: CliConnectRequest) {
  if (request.new !== undefined) return void connectNew(request.request, request.new);
  const profileId = profileNamed(request.profile);
  if (!profileId) return quietly(replyCliConnect({ request: request.request, allow: false }));
  if (useCliConnect.getState().requests.some((r) => r.id === request.request)) return;
  const pending: PendingConnect = { id: request.request, agent: request.agent || "An agent", profileId, profileName: useBrowser.getState().profiles[profileId]!.name };
  useCliConnect.setState((c) => ({ requests: [...c.requests, pending] }));
  if (AppState.currentState !== "active") void notify(pending);
}

async function notify(pending: PendingConnect) {
  const title = connectTitle(pending);
  if (backgroundInstance) return console.info(`[cli] would notify: ${title}`);
  try {
    if ((await notificationPermission()) === "notDetermined") await requestNotificationPermission();
    if (!useCliConnect.getState().requests.some((r) => r.id === pending.id)) return;
    await postNotification({
      id: NOTIFICATION + pending.id,
      title,
      body: "It can open and control pages in that profile until it disconnects.",
      allowDeny: true,
      data: { cliConnect: pending.id },
    });
  } catch (error) {
    console.warn("[cli] couldn't post the connect notification", error);
  }
}

export const connectTitle = (pending: Pick<PendingConnect, "agent" | "profileName">) => `${pending.agent} wants to use ${pending.profileName}`;

function drop(id: string) {
  const { requests } = useCliConnect.getState();
  if (!requests.some((r) => r.id === id)) return false;
  useCliConnect.setState({ requests: requests.filter((r) => r.id !== id) });
  if (!backgroundInstance) quietly(removeNotifications([NOTIFICATION + id]));
  return true;
}

export function answerConnect(id: string, allow: boolean) {
  const pending = useCliConnect.getState().requests.find((r) => r.id === id);
  if (!pending || !drop(id)) return;
  const profile = useBrowser.getState().profiles[pending.profileId];
  quietly(replyCliConnect(allow && profile ? { request: id, allow: true, profile: pending.profileId } : { request: id, allow: false }));
}

export function sessionsChanged({ sessions }: { sessions: CliSession[] }) {
  const next = Array.isArray(sessions) ? sessions : [];
  const known = new Set(useCliConnect.getState().sessions.map((x) => x.id));
  useCliConnect.setState({ sessions: next });
  const s = useBrowser.getState();
  const joined = new Set(next.filter((x) => !known.has(x.id) && isAgentProfile(s, x.profile)).map((x) => x.profile));
  for (const profile of joined) wakeProfileTabs(profile);
}

function renamed({ profile, name }: { profile: string; name: string }) {
  const s = useBrowser.getState();
  if (isAgentProfile(s, profile) && name.trim()) s.updateProfile(profile, { name: name.trim() });
}

export const useAgentConnected = (profileId: string): boolean => useCliConnect((c) => c.sessions.some((x) => x.profile === profileId));

export const usePendingConnect = () => useCliConnect((c) => c.requests[0] ?? null);

let started = false;

export function startCliConnect() {
  if (started) return;
  started = true;
  onCliConnectRequest(received);
  onCliConnectCancel(({ request }) => void drop(request));
  onCliSessions(sessionsChanged);
  onCliRename(renamed);
  onGatewayActivity(({ active }) => noteGatewayActive(gatewayOn && active));
  onNotificationResponse((response) => {
    const id = (response.data as { cliConnect?: unknown } | null)?.cliConnect;
    if (typeof id !== "string") return;
    if (response.action === "allow" || response.action === "deny") answerConnect(id, response.action === "allow");
  });
  const pushShown = startGatewayTabs(controlOn);
  startSessionRuns();
  const follow = (engineOn: boolean) => {
    if (engineOn === wanted) return;
    wanted = engineOn;
    const attempt = ++attempts;
    void (engineOn ? startGateway() : stopGateway()).then(
      (status) => {
        if (attempt !== attempts) return;
        gatewayOn = engineOn && status?.state === "on";
        if (!gatewayOn) return void clearGateway();
        void pushProfiles(true);
        pushShown();
      },
      () => {
        if (attempt !== attempts) return;
        gatewayOn = false;
        clearGateway();
      },
    );
  };
  useCli.subscribe((c) => follow(c.server?.state === "on"));
  useBrowser.subscribe((s, prev) => {
    if (s.profiles !== prev.profiles || s.profileOrder !== prev.profileOrder) void pushProfiles();
  });
  follow(useCli.getState().server?.state === "on");
}

let wanted = false;
let attempts = 0;

function clearGateway() {
  sentProfiles = null;
  noteGatewayActive(false);
  useCliConnect.setState({ requests: [], sessions: [] });
}

if (__DEV__) (globalThis as { acCliConnect?: unknown }).acCliConnect = { store: useCliConnect, received, cancelled: drop, sessionsChanged, renamed, answerConnect, cliProfiles: () => cliProfiles(useBrowser.getState()) };
