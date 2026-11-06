import { component$, useSignal, useVisibleTask$, type Signal } from "@builder.io/qwik";
import { api } from "../lib/api";

/**
 * Cloudflare Turnstile challenge for the anonymous write forms (signup, magic
 * link). The site key comes from `GET /auth/providers` at runtime; when the
 * API has no key configured the component renders nothing and `token` stays
 * `""`, so forms keep working exactly as before. `ready` flips to `true` once
 * we know whether a challenge is needed; `token` carries the response the API
 * expects as `turnstile_token`.
 */
const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=__accountsTurnstileReady";
const READY_CALLBACK = "__accountsTurnstileReady";

type TurnstileApi = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id?: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
    [READY_CALLBACK]?: () => void;
  }
}

let loader: Promise<TurnstileApi> | null = null;
function loadTurnstile(): Promise<TurnstileApi> {
  if (loader) return loader;
  loader = new Promise<TurnstileApi>((resolve, reject) => {
    if (window.turnstile) return resolve(window.turnstile);
    window[READY_CALLBACK] = () => window.turnstile && resolve(window.turnstile);
    const s = document.createElement("script");
    s.src = SCRIPT_SRC;
    s.async = true;
    s.defer = true;
    s.onerror = () => reject(new Error("turnstile script failed"));
    document.head.appendChild(s);
  });
  return loader;
}

interface Props {
  /** Receives the challenge token ("" until solved / when the challenge is off). */
  token: Signal<string>;
  /** `true` once the component knows whether a challenge is required. */
  ready: Signal<boolean>;
  /** `true` while a challenge is required and not yet solved. */
  required: Signal<boolean>;
  /** Appearance of the Cloudflare widget. */
  theme?: "light" | "dark" | "auto";
}

export const Turnstile = component$<Props>(({ token, ready, required, theme = "auto" }) => {
  const container = useSignal<HTMLDivElement>();
  const siteKey = useSignal<string | null>(null);

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    let key: string | null = null;
    try {
      key = (await api.providers()).turnstile_site_key ?? null;
    } catch {
      key = null;
    }
    siteKey.value = key;
    required.value = !!key;
    ready.value = true;
    if (!key || !container.value) return;
    try {
      const ts = await loadTurnstile();
      ts.render(container.value, {
        sitekey: key,
        theme,
        callback: (t: string) => {
          token.value = t;
          required.value = false;
        },
        "expired-callback": () => {
          token.value = "";
          required.value = true;
        },
        "error-callback": () => {
          token.value = "";
          required.value = true;
        },
      });
    } catch {
      // Script blocked (ad blocker / offline): the API fails open when
      // Cloudflare is unreachable on its side, but a blocked script on ours
      // leaves no token. Let the submit go through and the API decide.
      required.value = false;
    }
  });

  if (siteKey.value === null) return null;
  return <div ref={container} data-testid="turnstile" class="min-h-[65px]" />;
});
