import {
  call,
  on,
  type CliConnectReply,
  type CliConnectRequest,
  type CliRename,
  type CliSession,
  type GatewayActivity,
  type GatewayCloseTab,
  type GatewayOpenTab,
  type GatewayProfile,
  type GatewayRun,
  type GatewayRunReply,
} from "@ardia/ardiacore";

export type { CliConnectRequest, CliSession, GatewayOpenTab, GatewayProfile, GatewayRun, GatewayRunReply };

export const startGateway = () => call("gateway.start");
export const stopGateway = () => call("gateway.stop");
export const setGatewayProfiles = (profiles: GatewayProfile[]) => call("gateway.profiles", { profiles });
export const setGatewayShownTabs = (tabs: Record<string, string>) => call("gateway.shownTabs", { tabs });
export const replyCliConnect = (reply: CliConnectReply) => call("gateway.connectReply", reply);
export const endCliSessions = (profile: string) => call("gateway.endSessions", { profile });
export const replyGatewayRun = (reply: GatewayRunReply) => call("gateway.runReply", reply);
export const gatewayTabOpened = (request: string, tabId: string | null) => call("gateway.tabOpened", { request, tabId });

export const onCliConnectRequest = (listener: (request: CliConnectRequest) => void) => on("gateway.connectRequest", listener);
export const onCliConnectCancel = (listener: (cancel: { request: string }) => void) => on("gateway.connectCancel", listener);
export const onCliSessions = (listener: (sessions: { sessions: CliSession[] }) => void) => on("gateway.sessions", listener);
export const onCliRename = (listener: (rename: CliRename) => void) => on("gateway.rename", listener);
export const onGatewayOpenTab = (listener: (open: GatewayOpenTab) => void) => on("gateway.openTab", listener);
export const onGatewayCloseTab = (listener: (close: GatewayCloseTab) => void) => on("gateway.closeTab", listener);
export const onGatewayRun = (listener: (run: GatewayRun) => void) => on("gateway.run", listener);
export const onGatewayActivity = (listener: (activity: GatewayActivity) => void) => on("gateway.activity", listener);
