/**
 * `return_to` handling (CONTRACT.md → Hosted pages / CSRF-CORS).
 *
 * Every hosted page accepts `?return_to=<url>`. Only URLs on an allowed origin
 * are honoured — this app's own origin, `3m4.net` and any `*.3m4.net` host
 * over https, and `localhost` / `127.0.0.1` on any port over http for local
 * development. Root-relative paths are always fine. Anything else (including
 * protocol-relative `//evil`) falls back to `/profile`, so the pages can never
 * be used as an open redirect.
 */
import { normalizeLang } from "../i18n/langs";

export const DEFAULT_RETURN = "/profile";

function appOrigin(): string | null {
  const configured = import.meta.env.VITE_APP_URL;
  if (configured && /^https?:\/\//.test(configured)) {
    try {
      return new URL(configured).origin;
    } catch {
      /* fall through */
    }
  }
  if (typeof location !== "undefined") return location.origin;
  return null;
}

export function isAllowedReturn(value: string): boolean {
  if (!value) return false;
  if (value.startsWith("/")) return !value.startsWith("//");
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  if (url.origin === appOrigin()) return true;
  const host = url.hostname.toLowerCase();
  if (url.protocol === "https:" && (host === "3m4.net" || host.endsWith(".3m4.net"))) return true;
  if (url.protocol === "http:" && (host === "localhost" || host === "127.0.0.1")) return true;
  return false;
}

/** The validated `return_to` from a URL's query, or the default. */
export function readReturnTo(url: URL | { searchParams: URLSearchParams }): string {
  const raw = url.searchParams.get("return_to") || "";
  return isAllowedReturn(raw) ? raw : DEFAULT_RETURN;
}

/**
 * The `lang` a relying site handed over (CONTRACT.md → Hosted pages), as a
 * supported locale code, or undefined when absent / unknown. Carried along
 * the hops between the hosted pages so the language survives them.
 */
export function readLang(url: URL | { searchParams: URLSearchParams }): string | undefined {
  return normalizeLang(url.searchParams.get("lang")) ?? undefined;
}

/**
 * Append `return_to` (dropped when it is the default) and any extra params
 * (`lang`, `email`, …; undefined / empty values are skipped) to a local path.
 */
export function withReturnTo(path: string, returnTo: string, extra?: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  if (returnTo && returnTo !== DEFAULT_RETURN) params.set("return_to", returnTo);
  for (const [k, v] of Object.entries(extra ?? {})) if (v) params.set(k, v);
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** Navigate to a validated destination (cross-origin needs a real navigation). */
export function goTo(returnTo: string): void {
  location.assign(isAllowedReturn(returnTo) ? returnTo : DEFAULT_RETURN);
}
