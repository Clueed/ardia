import { pagerState, selectPager, stepPager, switchPager, type NativePagerConfig, type PagerStateEvent, type SwipeEvent } from "../../platform/pager";
import { useEffect, useLayoutEffect, useMemo } from "react";
import { Animated, unstable_batchedUpdates } from "react-native";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { useBrowser, type BrowserState } from "../browser/store";
import { AGENTS_PAGE, pageIdOf, pagerOrderOf } from "../browser/agents";

export type PagerPage = { id: string; slot: number; resting?: boolean };

const orders = new WeakMap<readonly string[], string[]>();

export function pagerOrder(s: Pick<BrowserState, "profileOrder">): string[] {
  let order = orders.get(s.profileOrder);
  if (!order) orders.set(s.profileOrder, (order = pagerOrderOf(s.profileOrder)));
  return order;
}

const windowPage = (s: BrowserState, windowId: string) => pageIdOf(s, s.windows[windowId]);

function goToPage(windowId: string, pageId: string) {
  const s = useBrowser.getState();
  if (pageId === AGENTS_PAGE) s.showAgentsPage(windowId);
  else s.switchProfile(windowId, pageId);
}

function restPages(current: string | null, order: string[]): PagerPage[] {
  if (!current) return [];
  const i = order.indexOf(current);
  const before = i > 0 ? order[i - 1] : undefined;
  const after = i >= 0 ? order[i + 1] : undefined;
  return [...(before ? [{ id: before, slot: -1 }] : []), { id: current, slot: 0 }, ...(after ? [{ id: after, slot: 1 }] : [])];
}

const WHEEL_THRESHOLD = 1;
const WHEEL_BURST_MS = 49;
const WHEEL_COOLDOWN_MS = 250;

class ProfilePager {
  readonly pos: Animated.Value;
  readonly state = create<{ pages: PagerPage[] | null; ack: number }>()(() => ({ pages: null, ack: 0 }));
  private surfaces = 0;
  private switching = false;
  private unsubscribe: () => void;
  private lastEvent: object | null = null;
  private wheelState = { sum: 0, last: 0, trigger: 0 };
  private external = 0;
  private externalGeneration = 0;

  readonly windowId: string;

  constructor(windowId: string) {
    this.windowId = windowId;
    this.pos = new Animated.Value(Math.max(0, this.index()), { useNativeDriver: true });
    this.state.setState({ pages: this.warmPages() });
    this.unsubscribe = useBrowser.subscribe((s, prev) => {
      const w = s.windows[windowId];
      if (!w) return this.dispose();
      const was = prev.windows[windowId];
      const page = pageIdOf(s, w);
      const before = pageIdOf(prev, was);
      if (page !== before || (w.kind === "private") !== (was?.kind === "private") || s.profileOrder !== prev.profileOrder) {
        this.state.setState({ pages: this.warmPages() });
      }
      if (!this.switching && page && page !== before) this.selectExternal(page, pagerOrder(s));
    });
  }

  attach() {
    this.surfaces++;
    return () => void this.surfaces--;
  }

  readonly onNativeState = (event: PagerStateEvent) => {
    if (this.external) return;
    this.commitNative(pagerState(this.windowId) ?? event, event);
  };

  private selectExternal(pageId: string, order: string[]) {
    const index = order.indexOf(pageId);
    if (index >= 0) this.pos.setValue(index);
    const generation = ++this.externalGeneration;
    this.external = generation;
    const done = (ok: boolean) => {
      if (this.external !== generation) return;
      this.external = 0;
      if (ok) this.commitNative(pagerState(this.windowId));
    };
    selectPager(this.windowId, pageId, order).then(done, () => done(false));
  }

  private commitNative(snapshot: Pick<PagerStateEvent, "sequence" | "selected" | "profileId"> | null, event?: PagerStateEvent) {
    if (!snapshot || snapshot.sequence <= this.state.getState().ack) return;
    if (__DEV__) this.lastEvent = { native: event ?? null, snapshot };
    const s = useBrowser.getState();
    const w = s.windows[this.windowId];
    const id = snapshot.profileId !== undefined ? snapshot.profileId : pagerOrder(s)[snapshot.selected];
    unstable_batchedUpdates(() => {
      if (w && w.kind !== "private" && id && (id === AGENTS_PAGE || s.profiles[id]) && id !== pageIdOf(s, w)) {
        this.switching = true;
        try {
          goToPage(this.windowId, id);
        } finally {
          this.switching = false;
        }
      }
      this.state.setState({ ack: snapshot.sequence });
    });
  }

  private index() {
    const current = this.current();
    return current ? pagerOrder(useBrowser.getState()).indexOf(current) : -1;
  }

  private warmPages(): PagerPage[] | null {
    const i = this.index();
    if (i < 0) return null;
    const order = pagerOrder(useBrowser.getState());
    return [i - 1, i, i + 1].filter((slot) => slot >= 0 && slot < order.length).map((slot) => ({ id: order[slot]!, slot }));
  }

  reapplyNativePosition() {
    this.pos.setOffset(0);
  }

  get active() {
    return this.surfaces > 0 && !!this.current();
  }

  wheel(e: SwipeEvent) {
    const now = Date.now();
    const w = this.wheelState;
    if (now - w.trigger <= WHEEL_COOLDOWN_MS) return;
    if (now - w.last > WHEEL_BURST_MS) w.sum = 0;
    w.last = now;
    w.sum += e.direction === "back" ? -e.distance : e.distance;
    if (Math.abs(w.sum) <= WHEEL_THRESHOLD) return;
    const delta = w.sum < 0 ? -1 : 1;
    w.sum = 0;
    w.trigger = now;
    this.step(delta);
  }

  step(delta: -1 | 1) {
    if (!this.current()) return;
    void stepPager(this.windowId, delta, false, pagerOrder(useBrowser.getState())).then((ok) => {
      if (ok) return;
      const next = pagerOrder(useBrowser.getState())[this.index() + delta];
      if (this.index() >= 0 && next) goToPage(this.windowId, next);
    });
  }

  switchTo(pageId: string) {
    const s = useBrowser.getState();
    const order = pagerOrder(s);
    const index = order.indexOf(pageId);
    if ((pageId !== AGENTS_PAGE && !s.profiles[pageId]) || !this.current() || index < 0) return;
    if (!this.active) return goToPage(this.windowId, pageId);
    void switchPager(this.windowId, index, order).then((ok) => {
      if (!ok) goToPage(this.windowId, pageId);
    });
  }

  private current() {
    return windowPage(useBrowser.getState(), this.windowId);
  }

  private dispose() {
    this.external = 0;
    this.externalGeneration++;
    this.unsubscribe();
    pagers.delete(this.windowId);
  }

  debug() {
    return { lastEvent: this.lastEvent, snapshot: pagerState(this.windowId), ack: this.state.getState().ack, surfaces: this.surfaces, warm: this.state.getState().pages };
  }
}

const pagers = new Map<string, ProfilePager>();

export function pagerFor(windowId: string): ProfilePager {
  let pager = pagers.get(windowId);
  if (!pager) pagers.set(windowId, (pager = new ProfilePager(windowId)));
  return pager;
}

export function pageToProfile(windowId: string, pageId: string) {
  pagerFor(windowId).switchTo(pageId);
}

export function usePagerSurface(windowId: string) {
  useEffect(() => pagerFor(windowId).attach(), [windowId]);
}

export function usePagerPages(windowId: string): { pages: PagerPage[]; paging: boolean; pager: ProfilePager } {
  const pager = pagerFor(windowId);
  const current = useBrowser((s) => pageIdOf(s, s.windows[windowId]) ?? s.windows[windowId]?.profileId ?? null);
  const incognito = useBrowser((s) => s.windows[windowId]?.kind === "private");
  const order = useBrowser(pagerOrder);
  const all = !incognito && !!current && order.includes(current);
  const everyPage = useMemo(() => order.map((id, slot) => ({ id, slot })), [order]);
  const resting = useMemo(() => (all ? null : restPages(current, order).map((p) => (p.id === current ? p : { ...p, resting: true }))), [all, current, order]);
  return { pages: resting ?? everyPage, paging: all, pager };
}

export function usePagerNativeConfig(windowId: string, width?: number): NativePagerConfig | undefined {
  const pager = pagerFor(windowId);
  const ack = pager.state((s) => s.ack);
  const [selected, count, order] = useBrowser(
    useShallow((s) => {
      const order = pagerOrder(s);
      const page = pageIdOf(s, s.windows[windowId]);
      const i = page ? order.indexOf(page) : -1;
      return [i, order.length, order] as const;
    }),
  );
  return useMemo(
    () => (selected >= 0 ? { key: windowId, selected, count, width: width || undefined, ack, order } : undefined),
    [windowId, selected, count, width, ack, order],
  );
}

export function useNativePagerPosition(windowId: string) {
  const pager = pagerFor(windowId);
  useLayoutEffect(() => pager.reapplyNativePosition());
}

export function usePageStyle(windowId: string, slot: number, width: number) {
  const { pos } = pagerFor(windowId);
  useNativePagerPosition(windowId);
  return useMemo(() => ({ transform: [{ translateX: Animated.multiply(Animated.add(pos, -slot), -width) }] }), [pos, slot, width]);
}

if (__DEV__) {
  (globalThis as { acPager?: unknown }).acPager = (windowId: string) => pagerFor(windowId);
}
