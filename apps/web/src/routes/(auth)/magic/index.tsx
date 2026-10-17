import { component$, useContext, useStore, useVisibleTask$, $ } from "@builder.io/qwik";
import { Link, useLocation, type DocumentHead } from "@builder.io/qwik-city";
import { api, ApiRequestError } from "../../../lib/api";
import { FeaturesContext } from "../../../lib/features";
import { setSessionUser } from "../../../lib/session";
import { goTo, readReturnTo, withReturnTo } from "../../../lib/returnTo";
import { capture, identify } from "../../../lib/analytics";
import { tr, trError, useI18n } from "../../../i18n";

/**
 * Magic link: without `?token=` it is the request form; with a token it POSTs
 * it on load (the mail links here, never to the API, so a GET from a mail
 * scanner cannot consume it) and redirects to `return_to`.
 */
export default component$(() => {
  const loc = useLocation();
  const i18n = useI18n();
  const features = useContext(FeaturesContext);
  const returnTo = readReturnTo(loc.url);
  const token = loc.url.searchParams.get("token") || "";
  const state = useStore({
    email: loc.url.searchParams.get("email") || "",
    phase: (token ? "consuming" : "form") as "form" | "sending" | "sent" | "consuming",
    error: "",
  });

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    if (!token) return;
    try {
      const res = await api.magicConsume(token);
      setSessionUser(res.user);
      identify(res.user.id);
      capture("login", { method: "magic" });
      goTo(returnTo);
    } catch (e) {
      // Fall back to the request form with the error above it, so the visitor
      // can ask for a new link right away instead of landing on a dead end.
      state.phase = "form";
      state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
    }
  });

  const send = $(async () => {
    state.error = "";
    state.phase = "sending";
    try {
      await api.magic(state.email.trim(), returnTo, i18n.lang);
      state.phase = "sent";
    } catch (e) {
      state.phase = "form";
      state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
    }
  });

  if (state.phase === "consuming") {
    return (
      <div class="card p-8 text-center">
        <p class="text-sm text-slate-500" data-testid="magic-consuming">
          {tr(i18n, "auth.magicConsuming")}
        </p>
      </div>
    );
  }

  if (!features["magic-link"]) {
    return (
      <div class="card p-8 text-center">
        <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.magicTitle")}</h1>
        <p class="mt-3 text-sm text-slate-500">{tr(i18n, "auth.magicDisabled")}</p>
        <Link href={withReturnTo("/login", returnTo)} class="btn-primary mt-6 w-full">
          {tr(i18n, "auth.backToLogin")}
        </Link>
      </div>
    );
  }

  if (state.phase === "sent") {
    return (
      <div class="card p-8 text-center" data-testid="magic-sent">
        <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.magicSentTitle")}</h1>
        <p class="mt-3 text-sm text-slate-500">{tr(i18n, "auth.magicSentBody", { email: state.email })}</p>
        <Link href={withReturnTo("/login", returnTo)} class="btn-ghost mt-6 w-full">
          {tr(i18n, "auth.backToLogin")}
        </Link>
      </div>
    );
  }

  return (
    <div class="card p-8">
      <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.magicTitle")}</h1>
      <p class="mt-1 text-sm text-slate-500">{tr(i18n, "auth.magicBody")}</p>
      <form class="mt-6 space-y-4" preventdefault:submit onSubmit$={send}>
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
        <button type="submit" class="btn-primary w-full" disabled={state.phase === "sending"} data-testid="submit">
          {state.phase === "sending" ? tr(i18n, "auth.magicSending") : tr(i18n, "auth.magicSend")}
        </button>
      </form>
      <p class="mt-6 text-center text-sm text-slate-500">
        <Link href={withReturnTo("/login", returnTo)} class="font-medium text-primary-600 hover:underline">
          {tr(i18n, "auth.backToLogin")}
        </Link>
      </p>
    </div>
  );
});

export const head: DocumentHead = { title: "Magic link — 3m4 accounts" };
