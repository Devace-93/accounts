import { component$, useVisibleTask$ } from "@builder.io/qwik";
import { useLocation, type DocumentHead } from "@builder.io/qwik-city";
import { api } from "../../../lib/api";
import { clearSession } from "../../../lib/session";
import { isAllowedReturn } from "../../../lib/returnTo";
import { capture, resetAnalytics } from "../../../lib/analytics";
import { tr, useI18n } from "../../../i18n";

/** POSTs the logout, then leaves for `return_to` (default: /login). */
export default component$(() => {
  const loc = useLocation();
  const i18n = useI18n();
  const raw = loc.url.searchParams.get("return_to") || "";
  const dest = raw && isAllowedReturn(raw) ? raw : "/login";

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    try {
      await api.logout();
      capture("logout");
    } catch {
      /* already logged out, or offline: either way the cookies are gone or useless */
    }
    clearSession();
    resetAnalytics();
    location.replace(dest);
  });

  return (
    <div class="card p-8 text-center">
      <p class="text-sm text-slate-500">{tr(i18n, "auth.loggingOut")}</p>
    </div>
  );
});

export const head: DocumentHead = { title: "Log out — 3m4 accounts" };
