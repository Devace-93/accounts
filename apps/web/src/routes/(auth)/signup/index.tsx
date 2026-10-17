import { component$, useComputed$, useContext, useSignal, useStore, useVisibleTask$, $ } from "@builder.io/qwik";
import { Link, useLocation, useNavigate, type DocumentHead } from "@builder.io/qwik-city";
import { api, ApiRequestError } from "../../../lib/api";
import { FeaturesContext } from "../../../lib/features";
import { getSession, setSessionUser } from "../../../lib/session";
import { goTo, readReturnTo, withReturnTo } from "../../../lib/returnTo";
import { capture, identify } from "../../../lib/analytics";
import { PasswordField } from "../../../components/password-field";
import { ProviderButtons } from "../../../components/provider-buttons";
import { tr, trError, useI18n } from "../../../i18n";

/** CONTRACT.md → Objects → handle. */
export const HANDLE_RE = /^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/;
const MIN_PASSWORD = 8;

/** Default handle from an email's local part: lowercase slug, ≤ 32 chars. */
export function handleFromEmail(email: string): string {
  const local = email.split("@")[0] || "";
  return local
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32)
    .replace(/-+$/g, "");
}

/** What the user types in the handle field, normalised on input. */
function normaliseHandle(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/-{2,}/g, "-").slice(0, 32);
}

export default component$(() => {
  const loc = useLocation();
  const nav = useNavigate();
  const i18n = useI18n();
  const features = useContext(FeaturesContext);
  const returnTo = readReturnTo(loc.url);

  const password = useSignal("");
  const confirm = useSignal("");
  const state = useStore({
    email: "",
    handle: "",
    handleTouched: false,
    name: "",
    confirmTouched: false,
    loading: false,
    error: "",
  });

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(async () => {
    if (await getSession()) goTo(returnTo);
  });

  // Shown as soon as the confirm field has content (or was blurred), so the
  // mismatch is visible while typing, not only after leaving the field.
  const mismatch = useComputed$(() => (state.confirmTouched || confirm.value.length > 0) && confirm.value !== password.value);
  const handleBad = useComputed$(() => state.handle.length > 0 && !HANDLE_RE.test(state.handle));
  const canSubmit = useComputed$(
    () =>
      !state.loading &&
      state.email.includes("@") &&
      password.value.length >= MIN_PASSWORD &&
      confirm.value === password.value &&
      (state.handle === "" || HANDLE_RE.test(state.handle)),
  );

  const submit = $(async () => {
    state.confirmTouched = true;
    if (confirm.value !== password.value || password.value.length < MIN_PASSWORD) return;
    state.error = "";
    state.loading = true;
    try {
      const res = await api.signup({
        email: state.email.trim(),
        password: password.value,
        handle: state.handle || undefined,
        name: state.name.trim() || undefined,
        lang: i18n.lang,
      });
      setSessionUser(res.user);
      identify(res.user.id);
      capture("signup", { method: "password" });
      // Per CONTRACT.md the destination is return_to (default /profile), where
      // the unverified banner offers the resend; /verify is for the mailed link.
      goTo(returnTo);
    } catch (e) {
      state.error = e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
      state.loading = false;
    }
  });

  if (!features.signups) {
    return (
      <div class="card p-8 text-center">
        <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.inviteOnlyTitle")}</h1>
        <p class="mt-3 text-sm text-slate-500">{tr(i18n, "auth.inviteOnlyBody")}</p>
        <p class="mt-6 text-sm text-slate-500">
          {tr(i18n, "auth.haveAccount")}{" "}
          <Link href={withReturnTo("/login", returnTo)} class="font-medium text-primary-600 hover:underline">
            {tr(i18n, "auth.logIn")}
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div class="card p-8">
      <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "auth.signupTitle")}</h1>
      <p class="mt-1 text-sm text-slate-500">{tr(i18n, "auth.signupSubtitle")}</p>

      <form class="mt-6 space-y-4" preventdefault:submit onSubmit$={submit}>
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
            onInput$={(_, el) => {
              state.email = el.value;
              if (!state.handleTouched) state.handle = handleFromEmail(el.value);
            }}
          />
        </div>
        <div>
          <label class="label" for="handle">
            {tr(i18n, "auth.handle")}
          </label>
          <div class="flex items-center">
            <span class="rounded-s-lg border border-e-0 border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-400">@</span>
            <input
              id="handle"
              type="text"
              class={["input rounded-s-none", handleBad.value ? "border-red-400" : ""]}
              data-testid="handle"
              autoComplete="username"
              spellcheck={false}
              minLength={3}
              maxLength={32}
              pattern="[a-z0-9][a-z0-9\-]{1,30}[a-z0-9]"
              aria-invalid={handleBad.value ? "true" : undefined}
              aria-describedby="handle-hint"
              value={state.handle}
              onInput$={(_, el) => {
                state.handleTouched = true;
                const v = normaliseHandle(el.value);
                state.handle = v;
                el.value = v;
              }}
            />
          </div>
          <p id="handle-hint" class={["mt-1 text-xs", handleBad.value ? "text-red-600" : "text-slate-400"]}>
            {handleBad.value ? tr(i18n, "auth.err.invalid_handle") : tr(i18n, "auth.handleHint")}
          </p>
        </div>
        <div>
          <label class="label" for="name">
            {tr(i18n, "auth.name")} <span class="text-slate-400">{tr(i18n, "common.optional")}</span>
          </label>
          <input
            id="name"
            type="text"
            class="input"
            data-testid="name"
            autoComplete="name"
            maxLength={80}
            value={state.name}
            onInput$={(_, el) => (state.name = el.value)}
          />
        </div>
        <PasswordField
          id="password"
          label={tr(i18n, "common.password")}
          value={password}
          autoComplete="new-password"
          minLength={MIN_PASSWORD}
          hint={tr(i18n, "auth.passwordHint")}
        />
        <PasswordField
          id="password-confirm"
          testId="password-confirm"
          label={tr(i18n, "auth.confirmPassword")}
          value={confirm}
          autoComplete="new-password"
          minLength={MIN_PASSWORD}
          error={mismatch.value ? tr(i18n, "auth.passwordsMismatch") : undefined}
          onBlur$={() => (state.confirmTouched = true)}
        />
        <button type="submit" class="btn-primary w-full" disabled={!canSubmit.value} data-testid="submit">
          {state.loading ? tr(i18n, "auth.creatingAccount") : tr(i18n, "auth.createAccount")}
        </button>
      </form>

      <ProviderButtons returnTo={returnTo} />

      <p class="mt-6 text-center text-sm text-slate-500">
        {tr(i18n, "auth.haveAccount")}{" "}
        <Link href={withReturnTo("/login", returnTo)} class="font-medium text-primary-600 hover:underline">
          {tr(i18n, "auth.logIn")}
        </Link>
      </p>
    </div>
  );
});

export const head: DocumentHead = { title: "Sign up — 3m4 accounts" };
