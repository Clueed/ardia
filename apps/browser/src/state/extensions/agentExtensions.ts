import { applyExtensionsSync, extensionsSyncState, onExtensionsChanged, uninstallExtension, type ExtensionsSyncState, type SyncedExtension } from "../../platform/extensions";
import { useBrowser } from "../browser/store";
import { AGENTS_PAGE, agentProfileIds } from "../browser/agents";
import { engineProfile } from "../browser/model";

type Mirrored = Extract<SyncedExtension, { syncable: true }>;

const MIRROR_DELAY_MS = 1500;

export function agentLead(): string | null {
  return agentProfileIds(useBrowser.getState().profiles)[0] ?? null;
}

export const extensionsEngineProfile = (profileId: string): string | null => {
  const s = useBrowser.getState();
  if (profileId !== AGENTS_PAGE) return engineProfile(s, profileId);
  const lead = agentLead();
  return lead ? engineProfile(s, lead) : null;
};

const engineOf = (profileId: string) => engineProfile(useBrowser.getState(), profileId);
const mirrored = (e: SyncedExtension): e is Mirrored => e.syncable && !!e.version;

const recordOf = (e: Mirrored) => ({ on: !e.userDisabled, inc: !!e.incognito, pin: !!e.pinned });
const sameRecord = (a: Mirrored, b: Mirrored) => JSON.stringify(recordOf(a)) === JSON.stringify(recordOf(b));

async function stateOf(profile: string): Promise<ExtensionsSyncState | null> {
  try {
    return await extensionsSyncState(profile);
  } catch {
    return null;
  }
}

async function mirrorInto(lead: ExtensionsSyncState, target: string) {
  const state = await stateOf(target);
  if (!state?.ready) return;
  const wanted = lead.extensions.filter(mirrored);
  const have = new Map(state.extensions.filter(mirrored).map((e) => [e.id, e]));
  const busy = new Set([...state.pending, ...state.queued]);
  for (const e of wanted) {
    const mine = have.get(e.id);
    if (busy.has(e.id) || (mine && sameRecord(mine, e))) continue;
    await applyExtensionsSync(target, { id: e.id, record: recordOf(e) }).catch((error: unknown) => console.warn(`[agents] extension ${e.id} into ${target}`, error));
  }
  const keep = new Set([...wanted.map((e) => e.id), ...lead.pending, ...lead.queued]);
  for (const e of state.extensions) {
    if (!e.syncable || keep.has(e.id)) continue;
    await uninstallExtension(e.id, target).catch((error: unknown) => console.warn(`[agents] remove ${e.id} from ${target}`, error));
  }
}

let running: Promise<void> | null = null;
let again = false;

async function mirrorAll(only?: string) {
  const ids = agentProfileIds(useBrowser.getState().profiles);
  if (ids.length < 2 && !only) return;
  const lead = await stateOf(engineOf(ids[0]!));
  if (!lead?.ready) return;
  for (const id of ids.slice(1)) if (!only || id === only) await mirrorInto(lead, engineOf(id));
}

function mirrorSoon() {
  if (running) {
    again = true;
    return;
  }
  running = new Promise<void>((resolve) => setTimeout(resolve, MIRROR_DELAY_MS))
    .then(() => mirrorAll())
    .finally(() => {
      running = null;
      if (again) {
        again = false;
        mirrorSoon();
      }
    });
}

export function seedAgentExtensions(profileId: string) {
  const lead = agentLead();
  if (!lead || lead === profileId) return;
  void mirrorAll(profileId);
}

let started = false;

export function startAgentExtensions() {
  if (started) return;
  started = true;
  onExtensionsChanged(({ profile }) => {
    const lead = agentLead();
    if (lead && profile === engineOf(lead)) mirrorSoon();
  });
}
