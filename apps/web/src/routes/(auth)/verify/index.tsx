import { component$, useStore, useVisibleTask$, $ } from "@builder.io/qwik";
import { Link, useLocation, type DocumentHead } from "@builder.io/qwik-city";
import { api, ApiRequestError, tryRefresh } from "../../../lib/api";
import { getSession, setSessionUser } from "../../../lib/session";
import { readReturnTo, withReturnTo } from "../../../lib/returnTo";
import { capture } from "../../../lib/analytics";
import type { User } from "../../../lib/types";
import { tr, trError, useI18n } from "../../../i18n";

/**
 * Email verification. With `?token=` the page POSTs it on load and shows the
 * result; without a token it is the "check your inbox" state after signup,
 * with a resend button (needs a session).
 */
export default component$(() => {
  const loc = useLocation();
  const i18n = useI18n();
  const returnTo = readReturnTo(loc.url);
  const token = loc.url.searchParams.get("token") || "";
  const state = useStore({
    phase: (token ? "consuming" : "loading") as "consuming" | "verified" | "failed" | "loading" | "inbox" | "anonymous",
    user: null as User | null,
    resend: "idle" as "idle" | "sending" | "sent",
    error: "",
  });

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    if (token) {
      try {
        const res = await api.verifyConsume(token);
        // The API re-issues the cookie when this browser holds the session; a
        // refresh covers the other case (verified in a different tab) so the
        // next app request carries email_verified=true right away.
        await tryRefresh();
        setSessionUser(res.user);
        state.user = res.user;
        state.phase = "verified";
        capture("email_verified");
      } catch (e) {
        state.phase = "failed";
        state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
      }
      return;
    }
    const user = await getSession(true);
    state.user = user;
    if (!user) state.phase = "anonymous";
    else state.phase = user.email_verified ? "verified" : "inbox";
  });

  const resend = $(async () => {
    state.resend = "sending";
    state.error = "";
    try {
      await api.verifyResend(i18n.lang);
      state.resend = "sent";
    } catch (e) {
      state.resend = "idle";
      state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
    }
  });

  if (state.phase === "consuming" || state.phase === "loading") {
    return (
      <div class="card p-8 text-center">
        <p class="text-sm text-slate-500">{state.phase === "consuming" ? tr(i18n, "auth.verifyConsuming") : tr(i18n, "common.loading")}</p>
      </div>
    );
  }

  if (state.phase === "verified") {
    return (
      <div class="card p-8 text-center" data-testid="verified">
        <div class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-green-100 text-green-700" aria-hidden="true">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <h1 class="mt-4 text-2xl font-bold text-slate-900">{tr(i18n, "auth.verifiedTitle")}</h1>
        <p class="mt-3 text-sm text-slate-500">{token ? tr(i18n, "auth.verifiedBody") : tr(i18n, "auth.alreadyVerified")}</p>
        <a href={returnTo} class="btn-primary mt-6 w-full" data-testid="continue">
          {tr(i18n, "common.continue")}
        </a>
      </div>
    );
  }

  if (state.phase === "failed") {
    return (
      <div class="card p-8 text-center">
        <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.verifyFailedTitle")}</h1>
        <p class="mt-3 text-sm text-red-700" role="alert" data-testid="error">
          {state.error}
        </p>
        <Link href={withReturnTo("/verify", returnTo)} class="btn-primary mt-6 w-full">
          {tr(i18n, "auth.verifyResend")}
        </Link>
        <Link href={withReturnTo("/login", returnTo)} class="btn-ghost mt-2 w-full">
          {tr(i18n, "auth.backToLogin")}
        </Link>
      </div>
    );
  }

  if (state.phase === "anonymous") {
    return (
      <div class="card p-8 text-center">
        <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.verifyTitle")}</h1>
        <p class="mt-3 text-sm text-slate-500">{tr(i18n, "auth.verifyNeedLogin")}</p>
        <Link href={withReturnTo("/login", withReturnTo("/verify", returnTo))} class="btn-primary mt-6 w-full">
          {tr(i18n, "auth.logIn")}
        </Link>
      </div>
    );
  }

  return (
    <div class="card p-8 text-center" data-testid="verify-inbox">
      <div class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-primary-50 text-primary-700" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3 7l9 6 9-6" />
        </svg>
      </div>
      <h1 class="mt-4 text-2xl font-bold text-slate-900">{tr(i18n, "auth.verifyTitle")}</h1>
      <p class="mt-3 text-sm text-slate-500">{tr(i18n, "auth.verifyCheckInbox", { email: state.user?.email ?? "" })}</p>
      {state.error && (
        <p class="mt-3 text-sm text-red-700" role="alert" data-testid="error">
          {state.error}
        </p>
      )}
      <div class="mt-6 flex flex-col gap-2">
        {state.resend === "sent" ? (
          <p class="alert-ok">{tr(i18n, "auth.verifyResent")}</p>
        ) : (
          <button type="button" class="btn-secondary w-full" disabled={state.resend === "sending"} onClick$={resend} data-testid="resend-verification">
            {state.resend === "sending" ? tr(i18n, "auth.verifyResending") : tr(i18n, "auth.verifyResend")}
          </button>
        )}
        <a href={returnTo} class="btn-ghost w-full" data-testid="continue">
          {tr(i18n, "common.continue")}
        </a>
      </div>
    </div>
  );
});

export const head: DocumentHead = { title: "Verify your email — 3m4 accounts" };
