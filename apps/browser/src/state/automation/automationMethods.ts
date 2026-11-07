import { automationCommands } from "./automationCommands";
import { AUTOMATION_EVENTS, MIN_IDLE_SECONDS, NAMED_ONLY_EVENTS, type AutomationEventName } from "./eventNames";

export const PROTOCOL = 3;

export type ErrorCode = "bad_request" | "unknown_method" | "unknown_command" | "refused" | "no_window" | "failed";
export type MethodError = { code: ErrorCode; message: string };
export type RequestId = number | string | null;
export type ParsedRequest = { id: RequestId; method: string; params: Record<string, unknown> };
export type Subscription = {
  events: ReadonlySet<AutomationEventName>;
  fullUrls: boolean;
  tabIdle: ReadonlySet<number>;
  userIdle: ReadonlySet<number>;
  hooks: unknown;
};

export const SOCKET_RUN_REFUSED = "ardia run needs a session: run ardia connect, then pass --session.";

export const failure = (code: ErrorCode, message: string) => ({ error: { code, message } satisfies MethodError });

const isFields = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

export function parseRequest(line: string): ParsedRequest | { id: RequestId; error: MethodError } {
  let doc: unknown;
  try {
    doc = JSON.parse(line);
  } catch {
    return { id: null, ...failure("bad_request", "The line isn't JSON.") };
  }
  if (!isFields(doc)) return { id: null, ...failure("bad_request", "A request is a JSON object.") };
  const id = doc.id;
  const usable = typeof id === "string" || (typeof id === "number" && Number.isSafeInteger(id));
  if (!usable) return { id: null, ...failure("bad_request", "A request needs an id: a safe integer or a string.") };
  if (typeof doc.method !== "string") return { id, ...failure("bad_request", "A request needs a method.") };
  if (doc.params !== undefined && !isFields(doc.params)) return { id, ...failure("bad_request", "params must be an object.") };
  return { id, method: doc.method, params: (doc.params as Record<string, unknown> | undefined) ?? {} };
}

export const hello = (version: string) => ({ app: "Ardia", version, protocol: PROTOCOL });

export const commands = automationCommands;

const KNOWN_EVENTS: ReadonlySet<string> = new Set(AUTOMATION_EVENTS);
const MAX_THRESHOLDS = 8;

function thresholds(value: unknown): Set<number> | null {
  if (value === undefined) return new Set();
  if (!Array.isArray(value) || value.length > MAX_THRESHOLDS || !value.every((v) => Number.isSafeInteger(v) && v >= MIN_IDLE_SECONDS && v <= 7 * 86400)) return null;
  return new Set(value as number[]);
}

export function parseSubscription(params: Record<string, unknown>): Subscription | { error: MethodError } {
  const { events, fullUrls, idle, hooks } = params;
  if (!Array.isArray(events) || !events.every((name) => typeof name === "string")) return failure("bad_request", "subscribe needs events: a list of event names, or [\"*\"].");
  const unknown = events.filter((name) => name !== "*" && !KNOWN_EVENTS.has(name));
  if (unknown.length) return failure("bad_request", `Unknown events: ${unknown.join(", ")}. Events: ${AUTOMATION_EVENTS.join(", ")}.`);
  const named = events.filter((name) => name !== "*") as AutomationEventName[];
  const all = events.includes("*") ? AUTOMATION_EVENTS.filter((name) => !NAMED_ONLY_EVENTS.has(name)) : [];
  if (fullUrls !== undefined && typeof fullUrls !== "boolean") return failure("bad_request", "fullUrls must be true or false.");
  const idleFields = idle === undefined ? {} : idle;
  if (typeof idleFields !== "object" || idleFields === null || Array.isArray(idleFields)) return failure("bad_request", "idle is {\"tab\": [seconds], \"user\": [seconds]}.");
  const tabIdle = thresholds((idleFields as Record<string, unknown>).tab);
  const userIdle = thresholds((idleFields as Record<string, unknown>).user);
  if (!tabIdle || !userIdle) return failure("bad_request", `idle thresholds are lists of at most ${MAX_THRESHOLDS} whole seconds, at least ${MIN_IDLE_SECONDS}.`);
  return { events: new Set([...all, ...named]), fullUrls: fullUrls === true, tabIdle, userIdle, hooks };
}
