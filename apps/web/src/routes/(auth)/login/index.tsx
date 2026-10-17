import { component$, useContext, useSignal, useStore, useVisibleTask$, $ } from "@builder.io/qwik";
import { Link, useLocation, type DocumentHead } from "@builder.io/qwik-city";
import { api, ApiRequestError } from "../../../lib/api";
import { FeaturesContext } from "../../../lib/features";
import { getSession, setSessionUser } from "../../../lib/session";
import { goTo, readReturnTo, withReturnTo } from "../../../lib/returnTo";
import { capture, identify } from "../../../lib/analytics";
import { PasswordField } from "../../../components/password-field";
import { PROVIDER_NAMES, ProviderButtons } from "../../../components/provider-buttons";
import type { Provider } from "../../../lib/types";
import { tr, trError, useI18n } from "../../../i18n";

export default component$(() => {
  const loc = useLocation();
  const i18n = useI18n();
  const features = useContext(FeaturesContext);
  const returnTo = readReturnTo(loc.url);
  const password = useSignal("");
  const state = useStore({ email: "", loading: false, error: "" });

  // OAuth callback failures land here with ?error=oauth_failed&provider=…
  const oauthError = loc.url.searchParams.get("error");
  const oauthProvider = (loc.url.searchParams.get("provider") || "") as Provider;

  // Already signed in? Straight to the destination.
  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    if (await getSession()) goTo(returnTo);
  });

  const submit = $(async () => {
    state.error = "";
    state.loading = true;
    try {
      const res = await api.login(state.email.trim(), password.value);
      setSessionUser(res.user);
      identify(res.user.id);
      capture("login", { method: "password" });
      goTo(returnTo);
    } catch (e) {
      state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
      state.loading = false;
    }
  });

  return (
    <div class="card p-8">
      <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.loginTitle")}</h1>
      <p class="mt-1 text-sm text-slate-500">{tr(i18n, "auth.loginSubtitle")}</p>

      <form class="mt-6 space-y-4" preventdefault:submit onSubmit$={submit} noValidate={false}>
        {oauthError && !state.error && (
          <div class="alert-error" role="alert" data-testid="error">
            {oauthError === "oauth_email_unverified"
              ? tr(i18n, "auth.err.oauth_email_unverified")
              : tr(i18n, "auth.err.oauth_failed", { provider: PROVIDER_NAMES[oauthProvider] ?? oauthProvider ?? "" })}
          </div>
        )}
        {state.error && (
          <div class="alert-error" role="alert" data-testid="error">
            {state.error}
          </div>
        )}
        <div>
          <label class="label" for="email">
            {tr(i18n, "common.email")}
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            class="input"
            data-testid="email"
            value={state.email}
            onInput$={(_, el) => (state.email = el.value)}
          />
        </div>
        <PasswordField id="password" label={tr(i18n, "common.password")} value={password} autoComplete="current-password" />
        <button type="submit" class="btn-primary w-full" disabled={state.loading} data-testid="submit">
          {state.loading ? tr(i18n, "auth.loggingIn") : tr(i18n, "auth.loginTitle")}
        </button>
        {features["magic-link"] && (
          <p class="text-center text-sm">
            {/* A plain anchor whose destination is computed at click time, so the
                email typed so far always travels along (a reactive href can lag
                one render behind a fast click). */}
            <a
              href={withReturnTo("/magic", returnTo)}
              class="font-medium text-primary-600 hover:underline"
              data-testid="magic-link"
              preventdefault:click
              onClick$={() => {
                location.assign(withReturnTo("/magic", returnTo, state.email ? { email: state.email } : undefined));
              }}
            >
              {tr(i18n, "auth.magicLinkCta")}
            </a>
          </p>
        )}
      </form>

      <ProviderButtons returnTo={returnTo} />

      {features.signups && (
        <p class="mt-6 text-center text-sm text-slate-500">
          {tr(i18n, "auth.noAccount")}{" "}
          <Link href={withReturnTo("/signup", returnTo)} class="font-medium text-primary-600 hover:underline">
            {tr(i18n, "auth.signUp")}
          </Link>
        </p>
      )}
    </div>
  );
});

export const head: DocumentHead = { title: "Log in — 3m4 accounts" };
