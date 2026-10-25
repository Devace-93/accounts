import { component$, useContext, useSignal, useVisibleTask$ } from "@builder.io/qwik";
import { api, oauthStartUrl } from "../lib/api";
import { FeaturesContext } from "../lib/features";
import type { Provider } from "../lib/types";
import { tr, useI18n } from "../i18n";

export const PROVIDER_NAMES: Record<Provider, string> = {
  google: "Google",
  github: "GitHub",
  discord: "Discord",
};

export const ALL_PROVIDERS: Provider[] = ["google", "github", "discord"];

/** Monochrome brand marks (currentColor) so they read in both themes. */
export const ProviderIcon = component$<{ provider: Provider }>(({ provider }) => {
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", "aria-hidden": "true" } as const;
  switch (provider) {
    case "google":
      return (
        <svg {...common} fill="currentColor">
          <path d="M21.35 11.1h-9.17v2.73h6.51c-.33 3.81-3.5 5.44-6.5 5.44C8.36 19.27 5 16.25 5 12c0-4.1 3.2-7.27 7.2-7.27 3.09 0 4.9 1.97 4.9 1.97L19 4.72S16.56 2 12.1 2C6.42 2 2.03 6.8 2.03 12c0 5.05 4.13 10 10.22 10 5.35 0 9.25-3.67 9.25-9.09 0-1.15-.15-1.81-.15-1.81z" />
        </svg>
      );
    case "github":
      return (
        <svg {...common} fill="currentColor">
          <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
        </svg>
      );
    case "discord":
      return (
        <svg {...common} fill="currentColor">
          <path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.865-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.74 19.74 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.058a.082.082 0 0 0 .031.056 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
        </svg>
      );
  }
});

interface Props {
  /** Where the OAuth callback should land (validated by the API too). */
  returnTo: string;
  /** Link to the current session instead of logging in (profile page). */
  link?: boolean;
  /** Providers to leave out (already linked). */
  exclude?: Provider[];
  /** Shows the "or continue with" divider above the buttons. */
  divider?: boolean;
}

/**
 * Google / GitHub / Discord buttons. Only providers the API has
 * credentials for (`GET /auth/providers`) are rendered, and nothing at all
 * while the `oauth` feature is off. Each button is a plain link to the
 * server-side OAuth start endpoint (full-page redirect, no popup).
 */
export const ProviderButtons = component$<Props>(({ returnTo, link = false, exclude = [], divider = true }) => {
  const i18n = useI18n();
  const features = useContext(FeaturesContext);
  const providers = useSignal<Provider[] | null>(null);

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    try {
      providers.value = (await api.providers()).providers;
    } catch {
      providers.value = [];
    }
  });

  if (!features.oauth) return null;
  const visible = (providers.value ?? []).filter((p) => !exclude.includes(p));
  if (providers.value !== null && visible.length === 0) return null;

  return (
    <div data-provider-buttons>
      {divider && (
        <div class="my-6 flex items-center gap-3 text-xs uppercase tracking-wide text-slate-400">
          <span class="h-px flex-1 bg-slate-200" aria-hidden="true" />
          <span>{tr(i18n, "auth.continueWith")}</span>
          <span class="h-px flex-1 bg-slate-200" aria-hidden="true" />
        </div>
      )}
      <div class={["grid gap-2", visible.length > 2 ? "sm:grid-cols-2" : ""]}>
        {providers.value === null && <div class="h-10 animate-pulse rounded-lg bg-slate-100" aria-hidden="true" />}
        {visible.map((p) => (
          <a
            key={p}
            href={oauthStartUrl(p, returnTo, link)}
            class="btn-secondary w-full justify-start"
            data-testid={`provider-${p}`}
            rel="nofollow"
          >
            <ProviderIcon provider={p} />
            <span>{link ? tr(i18n, "profile.link") + " " + PROVIDER_NAMES[p] : tr(i18n, "auth.continueWithProvider", { provider: PROVIDER_NAMES[p] })}</span>
          </a>
        ))}
      </div>
    </div>
  );
});
