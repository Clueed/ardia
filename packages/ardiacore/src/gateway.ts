export type GatewayStatus = { state: "on" | "off"; port?: number; reason?: string };

export type GatewayProfile = { id: string; key: string; name: string; kind: "real" | "agent" };

export type CliConnectRequest = { request: string; agent: string; profile?: string; new?: string };

export type CliSession = { id: string; profile: string; agent: string };

export type CliRename = { profile: string; name: string };

export type CliConnectReply = { request: string; allow: true; profile: string } | { request: string; allow: false };

export type GatewayOpenTab = { request: string; profile: string; url: string; background: boolean };

export type GatewayRun = { request: string; profile: string; command: string; arg: unknown; window: string | null };

export type GatewayRunReply = { request: string; result: unknown } | { request: string; error: { code: string; message: string } };

export type GatewayCloseTab = { tabId: string; profile: string };
