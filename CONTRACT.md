# accounts — Interface Contract

`accounts.3m4.net` is the single identity service for every app under
`3m4.net` (3m4 shortener, exp, retro, metrics, smart-docs, bubbles, kinegram,
info). One user, one password, one profile (handle, name, avatar), one session
that every app recognises. Apps keep their own workspaces, plans, billing and
data; they only stop owning identity.

This file is the shared contract between the accounts API (Flask), the hosted
pages (Qwik City), the `session.js` widget and every relying app. Keep it in
sync with the code.

## Hosts and ports

| Where | Host | Notes |
|---|---|---|
| Production | `https://accounts.3m4.net` | Routed by the 3m4 edge Caddy on the Hetzner box (`accounts-api-1:5000`, `accounts-web-1:3000`) |
| Local | `http://localhost:8085` | Own Caddy in `deploy/docker-compose.yml` (8080 3m4, 8081 exp, 8082 retro, 8083 metrics) |

Containers: `postgres` 5432, `redis` 6379, `api` 5000 (Flask, mounted at `/api`
plus `/.well-known/*` and `/avatars/*`), `worker` (outbox mail delivery),
`web` 3000 (Qwik City SSR: pages + `/session.js`), `migrate` (one-shot).
Compose project name `accounts`. Frontend tooling is Bun. Brand colour: Tailwind
**indigo**.

## Session model

- Logging in sets two cookies:
  - `3m4_session` — a signed JWT (EdDSA / Ed25519, header `kid`), TTL
    `SESSION_TTL_MIN` (15). `HttpOnly; Secure; SameSite=Lax; Path=/;
    Domain=COOKIE_DOMAIN` (`.3m4.net` in production, unset locally so the
    cookie is host-only on `localhost` and shared across ports).
  - `3m4_refresh` — opaque, stored **hashed** (sha256) in `sessions`, TTL
    `REFRESH_TTL_DAYS` (30), rotated on every refresh. `HttpOnly; Secure;
    SameSite=Lax; Path=/api/session; Domain=` *(host-only: accounts only)*.
- Every relying app verifies `3m4_session` **locally** (no call to accounts)
  with the public keys from `GET https://accounts.3m4.net/.well-known/jwks.json`
  (cache 10 min; refetch once on an unknown `kid`). The same JWT is also
  accepted as `Authorization: Bearer <jwt>` for non-browser clients. When
  both are present the **explicit bearer wins** over the ambient cookie (a
  client holding a cookie for one identity can still act as another on
  purpose); an app's own API keys sent as bearers are recognised by their
  prefix and never mistaken for a session.
- JWT claims:

  ```json
  {
    "iss": "https://accounts.3m4.net",
    "aud": "3m4",
    "sub": "<user uuid>",
    "sid": "<session uuid>",
    "email": "ana@example.com",
    "email_verified": true,
    "handle": "ana",
    "name": "Ana López",
    "avatar_url": "https://accounts.3m4.net/avatars/<user uuid>?v=3",
    "iat": 1760000000,
    "exp": 1760000900
  }
  ```

- Expired access token ⇒ the app answers `401 session_expired`; the client
  calls `POST /api/session/refresh` (credentials included) and retries once.
  No refresh cookie ⇒ `401 no_session` ⇒ redirect to `/login?return_to=`.
- Logout revokes the session row and clears both cookies. Access tokens
  already issued die within `SESSION_TTL_MIN`; clients also re-check
  `GET /api/session` when a tab regains focus, so the visible state updates
  within seconds.
- Email verification gate: `email_verified` travels in the JWT. A relying app
  rejects protected routes with `403 email_unverified` until it is true
  (signup still issues a session so the user can see the "check your inbox"
  state and resend). Magic-link logins and OAuth identities whose provider
  reports a verified email flip it automatically.

### CSRF / CORS

- Cookies are `SameSite=Lax`. Every state-changing accounts endpoint
  additionally requires `Content-Type: application/json` (HTML forms cannot
  send it; anything else is `415 unsupported_media_type`) or, for the avatar
  upload, the header `X-Requested-With: 3m4` (missing ⇒ `403 csrf_check_failed`).
  Avatars over 2 MB are `413 image_too_large`.
- CORS with credentials is allowed for origins matching `ALLOWED_ORIGINS`
  (default: `https://*.3m4.net`, `https://3m4.net`, `http://localhost:*`,
  `http://127.0.0.1:*`). The same list guards `return_to` redirects (open
  redirect protection): anything else falls back to `/profile`.

### Signing keys

- `SESSION_SIGNING_KEY` — base64url Ed25519 private key (32-byte seed).
  Generate: `python -m dbcore.cli genkey`. Its `kid` is the first 8 hex chars
  of the sha256 of the public key.
- `SESSION_PREVIOUS_PUBLIC_KEYS` — comma-separated base64url public keys that
  stay in the JWKS during a rotation (tokens signed by them still verify).

## REST API (all under `/api`; JSON; errors `{"error": {"code", "message", ...}}`)

### Auth
| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/auth/signup` | `{email, password, handle?, name?, lang?}` | 201 `{user}` + cookies; queues the verification mail. 400 `invalid_email` / `weak_password` (< 8 chars) / `invalid_handle` / `reserved_handle`, 409 `email_taken` / `handle_taken`, 403 `signups_disabled` |
| POST | `/auth/login` | `{email, password}` | 200 `{user}` + cookies. 401 `invalid_credentials` (same answer for unknown email, no password set, wrong password; constant-time) |
| POST | `/auth/magic` | `{email, return_to?, lang?}` | 202 `{}` always (no enumeration). Queues a mail with `https://accounts.3m4.net/magic?token=…&return_to=…` when the email exists; unknown emails get a "no account yet, sign up" mail |
| POST | `/auth/magic/consume` | `{token}` | 200 `{user, return_to}` + cookies; marks the email verified. `return_to` is the safe-guarded value stored with the token (default `/profile`). 400 `invalid_token` / `expired_token` / `used_token` |
| POST | `/auth/verify/consume` | `{token}` | 200 `{user, return_to}`; sets `email_verified_at`. When the caller already holds a session for that same user (the usual case: the mail link opened in the browser that signed up) the response re-issues both cookies, so the JWT carries `email_verified: true` immediately instead of at the next refresh. A caller without a session is not logged in. Same errors as above |
| POST | `/auth/verify/resend` | `{lang?}` (session) | 202 `{}`; 429 after 3/hour; 409 `already_verified` |
| GET | `/auth/providers` | — | `{providers: ["google","github","microsoft","discord"]}` (only those configured) |
| GET | `/auth/oauth/<provider>/start` | `?return_to=&link=1` | 302 to the provider; `state` (+ PKCE for providers that support it) kept in a signed, short-lived `3m4_oauth` cookie. `link=1` requires a session and links the identity to it instead of logging in |
| GET | `/auth/oauth/<provider>/callback` | provider params | 302 to `return_to` (default `/profile`) with cookies set. On failure 302 to `/login?error=oauth_failed&provider=`. New identity + unknown email ⇒ user created (handle derived from the provider login/name, de-duplicated with a numeric suffix; email verified when the provider says so). New identity + known email ⇒ **linked only if the provider reports the email verified**, else `oauth_email_unverified` |

Magic and verification links point at **pages** that POST the token
(`/magic`, `/verify`); a GET never consumes a token, so mail scanners cannot
burn it. Tokens: 32 random bytes, stored as sha256, single use, TTL 15 min
(magic) / 24 h (verify). Requesting a new token invalidates the previous ones
of the same kind.

### Session
| Method | Path | Response |
|---|---|---|
| GET | `/session` | 200 `{user, session: {id, expires_at}}` from the **access** cookie / bearer; 401 `no_session` / `session_expired`. Cheap and CORS-open to allowed origins: what the widget and apps poll |
| POST | `/session/refresh` | 200 `{user}` + rotated cookies (reads `3m4_refresh`). 401 `invalid_refresh` and both cookies cleared |
| POST | `/session/logout` | 204, cookies cleared. Body `{"all": true}` revokes every session of the user |
| GET | `/session/list` | `{items: [{id, current, user_agent, created_at, last_seen_at}]}` |
| DELETE | `/session/<id>` | 204 (own sessions only) |

### Me (session required)
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/me` | — | `{user, has_password, identities: [{provider, provider_email, created_at}]}` |
| PATCH | `/me` | `{name?, handle?}` | `{user}`; handle errors as in signup. Changing the handle is allowed but the UI warns that smart-docs public URLs change |
| PUT | `/me/password` | `{current_password?, new_password}` | 204. `current_password` is required when `has_password`; 401 `invalid_credentials`. Revokes every **other** session |
| PUT | `/me/avatar` | `multipart/form-data`, field `file` (png/jpeg/webp/gif ≤ 2 MB) | `{user}` with a bumped `avatar_url` version. Server crops to a centred square and stores 256×256 WebP. 400 `invalid_image` / 413 |
| DELETE | `/me/avatar` | — | `{user}` (back to the generated default) |
| DELETE | `/me/identities/<provider>` | — | 204; 409 `last_login_method` when it is the only way left to log in (no password, no other identity) |

### Public
| Method | Path | Response |
|---|---|---|
| GET | `/.well-known/jwks.json` | `{"keys": [{"kty":"OKP","crv":"Ed25519","kid","x","alg":"EdDSA","use":"sig"}]}`; `Cache-Control: public, max-age=600`. Served by the API at the host root (not under `/api`) |
| GET | `/avatars/<user_id>` | `image/webp` 256×256, `Cache-Control: public, max-age=86400`; `?v=` busts caches. Users without an upload get a generated SVG avatar (initials of name/handle on a colour derived from the id), `image/svg+xml`. Host root, no auth |
| GET | `/session.js` | the widget (served by `web`, `Cache-Control: public, max-age=300`, CORS `*`) |
| GET | `/api/features` | `{features: {signups, oauth, "magic-link", "site-building"}}` — the public switches the pages render from (metrics' pattern) |
| GET | `/healthz`, `/api/healthz` | `{"status":"ok"}` |

### Rate limits (Redis, per client IP unless noted)
signup 5/min · login 10/min · magic 3/min and 5/hour per email · verify resend
3/hour per user · avatar upload 10/hour per user · session refresh 60/min ·
default 120/min.

## Objects

```json
User {
  "id": "uuid",
  "email": "ana@example.com",
  "email_verified": true,
  "handle": "ana",
  "name": "Ana López",
  "avatar_url": "https://accounts.3m4.net/avatars/uuid?v=3",
  "created_at": "2026-10-16T00:00:00Z"
}
```

- `handle`: `^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$` (3–32 chars, lowercase,
  digits, single hyphens, no leading/trailing hyphen), unique, not in
  `packages/shared/reserved_handles.json`. Default at signup: slug of the email
  local part, de-duplicated with `-2`, `-3`…
- `name`: 1–80 chars, optional (defaults to the handle in the UI).
- `email`: stored lowercase, unique, max 255.

## Data model (Postgres)

```
users            id uuid pk, email unique, email_verified_at, password_hash (null = no password),
                 handle unique, name, avatar_version int default 0, created_at, updated_at
identities       id, user_id fk cascade, provider, provider_user_id, provider_email,
                 profile jsonb, created_at — unique (provider, provider_user_id)
sessions         id uuid pk (= sid), user_id fk cascade, refresh_hash unique, user_agent,
                 ip_hash, created_at, last_seen_at, expires_at, revoked_at
email_tokens     id, user_id fk cascade, kind (verify | magic), token_hash unique,
                 return_to, expires_at, used_at, created_at
avatars          user_id pk fk cascade, data bytea, content_type, updated_at
outbox           id, kind (email), user_id, payload jsonb, status, attempts,
                 next_attempt_at, last_error, created_at, sent_at   (retro's pattern)
```

## Mail

Outbound mail goes through the transactional outbox (same transaction as the
business write) and is delivered by the `worker` service over SMTP
(`SMTP_URL`, `MAIL_FROM`, `MAIL_ENABLED`; copied from retro). Production uses
Resend's SMTP endpoint. Templates (text + HTML, `en` and `es`, picked from the
`lang` the page sends, else `Accept-Language`, else `en`): `verify`,
`magic`, `magic_no_account`, `password_changed`.

## Hosted pages (web)

All accept `?return_to=<absolute url on an allowed origin>`; when absent the
destination is `/profile`. Signed-in visitors of `/login` and `/signup` are
sent straight to `return_to`.

| Path | Content |
|---|---|
| `/` | redirect: `/profile` when signed in, else `/login` |
| `/login` | email + password (show/hide toggle), "Email me a magic link", divider, provider buttons, link to signup |
| `/signup` | email, handle (prefilled from the email as you type, editable, availability hint), password + confirm (each with its own show/hide toggle, mismatch shown inline), provider buttons, link to login. Hidden behind the `signups` feature switch like the other apps |
| `/magic` | without `token`: the request form; with `token`: POSTs it on load and redirects to `return_to`; errors offer to request a new one |
| `/verify` | with `token`: consumes it and shows success + "Continue" to `return_to`; without: "check your inbox" with a resend button (session required) |
| `/profile` | avatar (upload/remove, preview), name, handle (with the smart-docs URL warning), email + verified badge + resend, password (set/change), linked providers (link/unlink), active sessions (revoke one / all), log out |
| `/logout` | POSTs logout then redirects to `return_to` or `/login` |

Chrome: the same language picker (34 locales, `3m4.lang`), theme toggle
(`3m4.theme`), footer and visual language as the other 3m4 apps.

## `session.js` widget (for static apps: info, kinegram, bubbles)

```html
<div id="session"></div>
<script src="https://accounts.3m4.net/session.js" data-mount="#session" defer></script>
```

- Renders, signed out: **Log in** · **Sign up** (links to the hosted pages with
  `return_to=location.href`). Signed in: avatar + handle; clicking opens a
  menu with **Profile** and **Log out**. Follows `3m4.theme` / `3m4.lang`
  (strings in en/es, falls back to en) and the host's `--accent` when present.
- Also exposes `window.m4session`:
  `get(): Promise<User|null>` (cached, re-fetched on `visibilitychange`),
  `onChange(cb)`, `login(returnTo?)`, `signup(returnTo?)`, `logout()`,
  `profile()`. Zero dependencies, < 4 KB gzipped, never throws into the host.
- Fetches `GET /api/session` with `credentials: "include"`; on
  `session_expired` tries one `POST /api/session/refresh`.
- The accounts origin is taken from the script's own `src`, so the same tag
  works locally (`http://localhost:8085/session.js`).

## Relying apps (how 3m4 / exp / retro / metrics / smart-docs / bubbles plug in)

- Verify the JWT (cookie `3m4_session` or bearer) with the JWKS; accept only
  `iss` = `ACCOUNTS_URL`, `aud` = `3m4`. Two env vars per app:
  `ACCOUNTS_URL` (public origin: issuer, redirects, the browser's session
  calls; `https://accounts.3m4.net` / `http://localhost:8085`) and
  `ACCOUNTS_INTERNAL_URL` (where the app's containers fetch the JWKS; default
  = `ACCOUNTS_URL`; on the shared `edge` docker network, locally and in
  production alike, `http://accounts-api-1:5000`). The frontend gets
  `VITE_ACCOUNTS_URL` = `ACCOUNTS_URL` at build time. Reference implementations live in
  `packages/relying-party/python/m4session.py` (framework-agnostic verifier +
  Flask decorator `@require_session` → `g.identity`) and
  `packages/relying-party/ts/` (fetch wrapper that refreshes once on
  `session_expired`, plus `getSession()`).
- Session-less requests to protected routes answer `401 no_session`; the
  client redirects to `${ACCOUNTS_URL}/login?return_to=`. Expired access
  tokens answer `401 session_expired`; the client POSTs
  `${ACCOUNTS_URL}/api/session/refresh` (credentials included) once and
  retries. `/auth/me`-style endpoints stay reachable for unverified users so
  the app can render its own "verify your email" banner; everything else is
  `403 email_unverified` until the claim flips.
- Local passwords, refresh tokens and the `register` / `login` / `refresh`
  / `logout` endpoints are removed from every app. Existing users and their
  data were dropped (decision 2026-10-16: no real users yet).
- First time a `sub` is seen: create the local user row (`identity_id = sub`,
  email, handle, name, avatar_url copied from the claims) plus whatever the
  app needs (workspace, membership). Keep those columns fresh from the claims
  on every request (cheap: it is a compare + optional UPDATE).
- `/login` and `/signup` in the app ⇒ `302 ${ACCOUNTS_URL}/login?return_to=<current url>`.
  Nav: avatar + handle linking to `${ACCOUNTS_URL}/profile`, and **Log out**
  calling `POST ${ACCOUNTS_URL}/api/session/logout` with credentials.
- Errors to the browser: `401 no_session`, `401 session_expired`,
  `403 email_unverified`. Each app's own API keys / project keys / MCP auth
  are unchanged.
- bubbles: the game never requires a session; when one exists it shows the
  player (handle + avatar) and submits scores with it.

## Feature switches (PostHog, prefix `accounts-`; defaults in `packages/shared/feature_flags.json`)
`signups` (on), `site-building` (off), `oauth` (on), `magic-link` (on).

## PostHog events
`signup{method: password|google|github|microsoft|discord}`, `login{method}`,
`magic_link_requested`, `email_verified`, `identity_linked{provider}`,
`avatar_updated`, `logout`. Person id = user id.
