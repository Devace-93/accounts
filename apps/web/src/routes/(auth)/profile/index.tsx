import { component$, useComputed$, useSignal, useStore, useVisibleTask$, $ } from "@builder.io/qwik";
import { useLocation, useNavigate, type DocumentHead } from "@builder.io/qwik-city";
import { api, ApiRequestError } from "../../../lib/api";
import { clearSession, setSessionUser } from "../../../lib/session";
import { withReturnTo } from "../../../lib/returnTo";
import { capture, resetAnalytics } from "../../../lib/analytics";
import type { Me, Provider, SessionRow } from "../../../lib/types";
import { PasswordField } from "../../../components/password-field";
import { ALL_PROVIDERS, PROVIDER_NAMES, ProviderIcon } from "../../../components/provider-buttons";
import { UnverifiedBanner } from "../../../components/unverified-banner";
import { tr, trError, useI18n, type I18nState } from "../../../i18n";

const HANDLE_RE = /^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])?$/;
const MIN_PASSWORD = 8;

function errorText(i18n: I18nState, e: unknown): string {
  return e instanceof ApiRequestError ? trError(i18n, e.error.code, e.error.message) : tr(i18n, "auth.err.network");
}

function when(iso: string | null | undefined, lang: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

/** A friendlier label than the raw user agent: browser · OS. */
function describeAgent(ua: string | null): string {
  if (!ua) return "";
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\//.test(ua)
      ? "Opera"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Firefox\//.test(ua)
          ? "Firefox"
          : /Safari\//.test(ua)
            ? "Safari"
            : "";
  const os = /Windows/.test(ua)
    ? "Windows"
    : /Android/.test(ua)
      ? "Android"
      : /iPhone|iPad/.test(ua)
        ? "iOS"
        : /Mac OS/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : "";
  return [browser, os].filter(Boolean).join(" · ") || ua.slice(0, 60);
}

export default component$(() => {
  const loc = useLocation();
  const nav = useNavigate();
  const i18n = useI18n();

  const me = useSignal<Me | null>(null);
  const sessions = useSignal<SessionRow[]>([]);
  const loadError = useSignal("");

  const form = useStore({ name: "", handle: "", saving: false, msg: "", error: "" });
  const avatar = useStore({ busy: false, error: "", version: 0 });
  const current = useSignal("");
  const next = useSignal("");
  const confirm = useSignal("");
  const pw = useStore({ confirmTouched: false, saving: false, msg: "", error: "" });
  const providers = useStore({ available: [] as Provider[], error: "" });
  const sess = useStore({ error: "" });

  const load = $(async () => {
    try {
      const data = await api.me();
      me.value = data;
      form.name = data.user.name ?? "";
      form.handle = data.user.handle;
      setSessionUser(data.user);
      const [list, prov] = await Promise.all([api.sessions().catch(() => ({ items: [] })), api.providers().catch(() => ({ providers: [] }))]);
      sessions.value = list.items;
      providers.available = prov.providers;
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 401) {
        clearSession();
        await nav(withReturnTo("/login", loc.url.pathname + loc.url.search));
        return;
      }
      loadError.value = errorText(i18n, e);
    }
  });

  // eslint-disable-next-line qwik/no-use-visible-task
  useVisibleTask$(() => {
    load();
  });

  const pwMismatch = useComputed$(() => pw.confirmTouched && confirm.value !== next.value);
  const pwCanSave = useComputed$(
    () => !pw.saving && next.value.length >= MIN_PASSWORD && confirm.value === next.value && (!me.value?.has_password || current.value.length > 0),
  );

  const saveProfile = $(async () => {
    if (!me.value) return;
    form.error = "";
    form.msg = "";
    const handle = form.handle.trim();
    if (!HANDLE_RE.test(handle)) {
      form.error = tr(i18n, "auth.err.invalid_handle");
      return;
    }
    form.saving = true;
    try {
      const patch: { name?: string; handle?: string } = {};
      if ((me.value.user.name ?? "") !== form.name.trim()) patch.name = form.name.trim();
      if (me.value.user.handle !== handle) patch.handle = handle;
      if (Object.keys(patch).length) {
        const res = await api.updateMe(patch);
        me.value = { ...me.value, user: res.user };
        setSessionUser(res.user);
      }
      form.msg = tr(i18n, "common.saved");
    } catch (e) {
      form.error = errorText(i18n, e);
    } finally {
      form.saving = false;
    }
  });

  const uploadAvatar = $(async (file: File | undefined) => {
    if (!file || !me.value) return;
    avatar.error = "";
    avatar.busy = true;
    try {
      const res = await api.uploadAvatar(file);
      me.value = { ...me.value, user: res.user };
      setSessionUser(res.user);
      avatar.version++;
      capture("avatar_updated");
    } catch (e) {
      avatar.error = errorText(i18n, e);
    } finally {
      avatar.busy = false;
    }
  });

  const removeAvatar = $(async () => {
    if (!me.value) return;
    avatar.error = "";
    avatar.busy = true;
    try {
      const res = await api.removeAvatar();
      me.value = { ...me.value, user: res.user };
      setSessionUser(res.user);
      avatar.version++;
    } catch (e) {
      avatar.error = errorText(i18n, e);
    } finally {
      avatar.busy = false;
    }
  });

  const savePassword = $(async () => {
    if (!me.value) return;
    pw.confirmTouched = true;
    if (confirm.value !== next.value || next.value.length < MIN_PASSWORD) return;
    pw.error = "";
    pw.msg = "";
    pw.saving = true;
    try {
      await api.setPassword(next.value, me.value.has_password ? current.value : undefined);
      me.value = { ...me.value, has_password: true };
      current.value = "";
      next.value = "";
      confirm.value = "";
      pw.confirmTouched = false;
      pw.msg = tr(i18n, "profile.passwordSaved");
      sessions.value = (await api.sessions().catch(() => ({ items: sessions.value }))).items;
    } catch (e) {
      pw.error = errorText(i18n, e);
    } finally {
      pw.saving = false;
    }
  });

  const unlink = $(async (provider: Provider) => {
    if (!me.value) return;
    if (!window.confirm(tr(i18n, "profile.unlinkConfirm", { provider: PROVIDER_NAMES[provider] }))) return;
    providers.error = "";
    try {
      await api.unlinkIdentity(provider);
      me.value = { ...me.value, identities: me.value.identities.filter((i) => i.provider !== provider) };
    } catch (e) {
      providers.error = errorText(i18n, e);
    }
  });

  const revoke = $(async (id: string) => {
    sess.error = "";
    try {
      await api.revokeSession(id);
      sessions.value = sessions.value.filter((s) => s.id !== id);
    } catch (e) {
      sess.error = errorText(i18n, e);
    }
  });

  const logout = $(async (all: boolean) => {
    try {
      await api.logout(all);
      capture("logout", { all });
    } catch {
      /* best effort */
    }
    clearSession();
    resetAnalytics();
    location.assign("/login");
  });

  if (loadError.value) {
    return (
      <div class="card p-8 text-center">
        <p class="text-sm text-red-700" role="alert" data-testid="error">
          {loadError.value}
        </p>
        <button type="button" class="btn-secondary mt-4" onClick$={load}>
          {tr(i18n, "common.retry")}
        </button>
      </div>
    );
  }

  const data = me.value;
  if (!data) {
    return (
      <div class="card p-8 text-center">
        <p class="text-sm text-slate-400">{tr(i18n, "common.loading")}</p>
      </div>
    );
  }

  const user = data.user;
  const linked = new Set(data.identities.map((i) => i.provider));
  const avatarSrc = `${user.avatar_url}${user.avatar_url.includes("?") ? "&" : "?"}r=${avatar.version}`;
  const linkReturn = loc.url.pathname;

  return (
    <div class="space-y-6">
      <header class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-2xl font-bold text-slate-900">{tr(i18n, "profile.title")}</h1>
          <p class="mt-1 text-sm text-slate-500">{tr(i18n, "profile.subtitle", { email: user.email })}</p>
        </div>
        <button type="button" class="btn-secondary" onClick$={() => logout(false)} data-testid="logout">
          {tr(i18n, "profile.logout")}
        </button>
      </header>

      {!user.email_verified && <UnverifiedBanner />}

      {/* ── Avatar ───────────────────────────────────────────────────────── */}
      <section class="card p-6">
        <h2 class="text-lg font-semibold text-slate-900">{tr(i18n, "profile.avatar")}</h2>
        <div class="mt-4 flex flex-wrap items-center gap-5">
          <img src={avatarSrc} alt="" width="96" height="96" class="h-24 w-24 rounded-full border border-slate-200 bg-slate-100 object-cover" data-testid="avatar-img" />
          <div class="flex flex-col gap-2">
            <div class="flex flex-wrap gap-2">
              <label class={["btn-secondary cursor-pointer", avatar.busy ? "pointer-events-none opacity-60" : ""]}>
                {avatar.busy ? tr(i18n, "profile.avatarUploading") : tr(i18n, "profile.avatarUpload")}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  class="sr-only"
                  data-testid="avatar-input"
                  disabled={avatar.busy}
                  onChange$={(_, el) => {
                    const f = el.files?.[0];
                    el.value = "";
                    uploadAvatar(f);
                  }}
                />
              </label>
              <button type="button" class="btn-ghost" disabled={avatar.busy} onClick$={removeAvatar} data-testid="avatar-remove">
                {tr(i18n, "profile.avatarRemove")}
              </button>
            </div>
            <p class="text-xs text-slate-400">{tr(i18n, "profile.avatarHint")}</p>
            {avatar.error && (
              <p class="text-xs text-red-700" role="alert">
                {avatar.error}
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── Profile details ──────────────────────────────────────────────── */}
      <section class="card p-6">
        <h2 class="text-lg font-semibold text-slate-900">{tr(i18n, "profile.details")}</h2>
        <form class="mt-4 space-y-4" preventdefault:submit onSubmit$={saveProfile}>
          {form.error && (
            <div class="alert-error" role="alert" data-testid="error">
              {form.error}
            </div>
          )}
          {form.msg && <div class="alert-ok">{form.msg}</div>}
          <div>
            <label class="label" for="name">
              {tr(i18n, "auth.name")}
            </label>
            <input id="name" type="text" class="input" maxLength={80} autoComplete="name" data-testid="name" value={form.name} onInput$={(_, el) => (form.name = el.value)} />
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
                class="input rounded-s-none"
                minLength={3}
                maxLength={32}
                spellcheck={false}
                autoComplete="username"
                data-testid="handle"
                value={form.handle}
                onInput$={(_, el) => (form.handle = el.value.toLowerCase())}
              />
            </div>
            <p class="mt-1 text-xs text-slate-400">{tr(i18n, "auth.handleHint")}</p>
            {form.handle !== user.handle && <p class="alert-warn mt-2 text-xs">{tr(i18n, "profile.handleWarning")}</p>}
          </div>
          <div>
            <span class="label">{tr(i18n, "profile.email")}</span>
            <div class="flex flex-wrap items-center gap-2 text-sm text-slate-700">
              <span>{user.email}</span>
              {user.email_verified ? (
                <span class="badge bg-green-100 text-green-800" data-testid="verified-badge">
                  {tr(i18n, "profile.verified")}
                </span>
              ) : (
                <span class="badge bg-amber-100 text-amber-800">{tr(i18n, "profile.unverified")}</span>
              )}
            </div>
          </div>
          <button type="submit" class="btn-primary" disabled={form.saving} data-testid="save-profile">
            {form.saving ? tr(i18n, "common.saving") : tr(i18n, "common.save")}
          </button>
        </form>
      </section>

      {/* ── Password ─────────────────────────────────────────────────────── */}
      <section class="card p-6">
        <h2 class="text-lg font-semibold text-slate-900">{tr(i18n, "profile.password")}</h2>
        {!data.has_password && <p class="mt-1 text-sm text-slate-500">{tr(i18n, "profile.noPassword")}</p>}
        <form class="mt-4 space-y-4" preventdefault:submit onSubmit$={savePassword}>
          {pw.error && (
            <div class="alert-error" role="alert" data-testid="error">
              {pw.error}
            </div>
          )}
          {pw.msg && <div class="alert-ok">{pw.msg}</div>}
          {data.has_password && (
            <PasswordField id="password-current" testId="password-current" label={tr(i18n, "auth.currentPassword")} value={current} autoComplete="current-password" />
          )}
          <PasswordField
            id="password"
            label={tr(i18n, "auth.newPassword")}
            value={next}
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
            error={pwMismatch.value ? tr(i18n, "auth.passwordsMismatch") : undefined}
            onBlur$={() => (pw.confirmTouched = true)}
          />
          <button type="submit" class="btn-primary" disabled={!pwCanSave.value} data-testid="save-password">
            {pw.saving ? tr(i18n, "common.saving") : data.has_password ? tr(i18n, "profile.changePassword") : tr(i18n, "profile.setPassword")}
          </button>
        </form>
      </section>

      {/* ── Linked accounts ──────────────────────────────────────────────── */}
      <section class="card p-6">
        <h2 class="text-lg font-semibold text-slate-900">{tr(i18n, "profile.providers")}</h2>
        <p class="mt-1 text-sm text-slate-500">{tr(i18n, "profile.providersBody")}</p>
        {providers.error && (
          <div class="alert-error mt-3" role="alert" data-testid="error">
            {providers.error}
          </div>
        )}
        <ul class="mt-4 divide-y divide-slate-200">
          {ALL_PROVIDERS.filter((p) => linked.has(p) || providers.available.includes(p)).map((p) => {
            const identity = data.identities.find((i) => i.provider === p);
            return (
              <li key={p} class="flex items-center justify-between gap-3 py-3" data-testid={`identity-${p}`}>
                <div class="flex items-center gap-3">
                  <span class="text-slate-600">
                    <ProviderIcon provider={p} />
                  </span>
                  <div>
                    <div class="text-sm font-medium text-slate-900">{PROVIDER_NAMES[p]}</div>
                    <div class="text-xs text-slate-400">{identity ? identity.provider_email || tr(i18n, "profile.linked") : tr(i18n, "profile.notLinked")}</div>
                  </div>
                </div>
                {identity ? (
                  <button type="button" class="btn-ghost" onClick$={() => unlink(p)} data-testid={`unlink-${p}`}>
                    {tr(i18n, "profile.unlink")}
                  </button>
                ) : (
                  <a href={`${(import.meta.env.VITE_API_URL || "/api").replace(/\/$/, "")}/auth/oauth/${p}/start?link=1&return_to=${encodeURIComponent(linkReturn)}`} class="btn-secondary" rel="nofollow" data-testid={`provider-${p}`}>
                    {tr(i18n, "profile.link")}
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* ── Sessions ─────────────────────────────────────────────────────── */}
      <section class="card p-6">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">{tr(i18n, "profile.sessions")}</h2>
            <p class="mt-1 text-sm text-slate-500">{tr(i18n, "profile.sessionsBody")}</p>
          </div>
          <button type="button" class="btn-danger" onClick$={() => logout(true)} data-testid="logout-all">
            {tr(i18n, "profile.logoutAll")}
          </button>
        </div>
        {sess.error && (
          <div class="alert-error mt-3" role="alert">
            {sess.error}
          </div>
        )}
        <ul class="mt-4 divide-y divide-slate-200">
          {sessions.value.map((s) => (
            <li key={s.id} class="flex items-center justify-between gap-3 py-3" data-testid="session-row">
              <div class="min-w-0">
                <div class="flex items-center gap-2 text-sm font-medium text-slate-900">
                  <span class="truncate">{describeAgent(s.user_agent) || tr(i18n, "profile.unknownDevice")}</span>
                  {s.current && <span class="badge bg-primary-50 text-primary-700">{tr(i18n, "profile.thisDevice")}</span>}
                </div>
                <div class="text-xs text-slate-400">
                  {s.last_seen_at ? tr(i18n, "profile.lastSeen", { when: when(s.last_seen_at, i18n.lang) }) : tr(i18n, "profile.signedInSince", { when: when(s.created_at, i18n.lang) })}
                </div>
              </div>
              {!s.current && (
                <button type="button" class="btn-ghost" onClick$={() => revoke(s.id)}>
                  {tr(i18n, "profile.revoke")}
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
});

export const head: DocumentHead = { title: "Your account — 3m4 accounts" };
