import { component$, useSignal, $ } from "@builder.io/qwik";
import { api, ApiRequestError } from "../lib/api";
import { tr, trError, useI18n } from "../i18n";

/**
 * Amber notice shown on /profile while `email_verified` is false, with a
 * resend button (rate limited server-side: 3/hour).
 */
export const UnverifiedBanner = component$(() => {
  const i18n = useI18n();
  const state = useSignal<"idle" | "sending" | "sent" | "error">("idle");
  const error = useSignal("");

  const resend = $(async () => {
    state.value = "sending";
    error.value = "";
    try {
      await api.verifyResend(i18n.lang);
      state.value = "sent";
    } catch (e) {
      state.value = "error";
      error.value = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
    }
  });

  return (
    <div class="alert-warn flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between" role="status" data-testid="unverified-banner">
      <span>{tr(i18n, "auth.unverifiedBanner")}</span>
      <div class="flex items-center gap-2">
        {state.value === "sent" ? (
          <span class="text-xs font-medium">{tr(i18n, "auth.verifyResent")}</span>
        ) : (
          <button type="button" class="btn-secondary whitespace-nowrap" disabled={state.value === "sending"} onClick$={resend} data-testid="resend-verification">
            {state.value === "sending" ? tr(i18n, "auth.verifyResending") : tr(i18n, "auth.verifyResend")}
          </button>
        )}
      </div>
      {error.value && <span class="text-xs text-red-700">{error.value}</span>}
    </div>
  );
});
