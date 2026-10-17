/**
 * Current-session state shared by every page.
 *
 * `getSession()` asks `GET /api/session` once and caches the answer; the cache
 * is dropped when the tab regains visibility (so a logout in another app's
 * tab shows up within seconds) and after any call that changes the session
 * (`setSessionUser` / `clearSession`). Pages consume it through `useSession()`.
 */
import { useStore, useVisibleTask$ } from "@builder.io/qwik";
import { api, ApiRequestError } from "./api";
import type { User } from "./types";

let cached: { user: User | null; at: number } | null = null;
let inFlight: Promise<User | null> | null = null;
let listening = false;

const TTL_MS = 30_000;

export async function getSession(force = false): Promise<User | null> {
  if (!force && cached && Date.now() - cached.at < TTL_MS) return cached.user;
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const res = await api.session();
      cached = { user: res.user, at: Date.now() };
    } catch (e) {
      // 401 no_session / session_expired (after one failed refresh) = signed out.
      // Network errors keep whatever we had so a blip does not log the UI out.
      if (e instanceof ApiRequestError) cached = { user: null, at: Date.now() };
      else if (!cached) cached = { user: null, at: 0 };
    } finally {
      inFlight = null;
    }
    return cached!.user;
  })();
  return inFlight;
}

export function setSessionUser(user: User | null): void {
  cached = { user, at: Date.now() };
}

export function clearSession(): void {
  cached = { user: null, at: Date.now() };
}

function listen(): void {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") cached = null;
  });
}

export interface SessionState {
  user: User | null;
  /** false until the first answer arrived (SSR never knows the viewer). */
  ready: boolean;
}

/** Component hook: resolves the session on the client, re-checks on focus. */
export function useSession(): SessionState {
  const state = useStore<SessionState>({ user: null, ready: false });
  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(({ cleanup }) => {
    listen();
    const load = async () => {
      state.user = await getSession();
      state.ready = true;
    };
    load();
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    cleanup(() => document.removeEventListener("visibilitychange", onVisible));
  });
  return state;
}
