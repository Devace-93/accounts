# accounts — project plan

Goal: one identity for every app under `3m4.net`. Decisions taken on
2026-10-16 (see the 3m4-info session that produced them):

- New repo `accounts` at `accounts.3m4.net`, same stack and chrome as metrics /
  retro, on the shared Hetzner box behind the 3m4 edge Caddy.
- Hosted auth pages with `return_to` redirects (one implementation of every
  form), not forms duplicated in each app.
- Shared cookie on `Domain=.3m4.net` carrying an Ed25519 JWT; apps verify it
  locally with the JWKS. Logout is global.
- Phase-1 providers: Google, GitHub, Microsoft, Discord. Facebook later (better
  sharing from the games).
- Magic links and mandatory email verification; mail through Resend.
- Global profile: handle (also smart-docs' public URL segment), name, avatar.
- No real users exist in any app yet: existing per-app users and their data
  are dropped, no migration of credentials.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Contract (`CONTRACT.md`), repo skeleton, deploy files, e2e suite | done (2026-10-16) |
| 2 | accounts service: dbcore, API (password, sessions, JWKS, verify, magic link, profile, avatars), worker, hosted pages, `session.js`, relying-party packages | done locally (2026-10-16): 40 pytest + 21 Playwright green on `make up` (:8085) |
| 3 | OAuth: Google, GitHub, Microsoft, Discord (app registrations by Enrique, see `deploy/PRODUCTION.md`) | code done, untested against real providers until client ids exist |
| 4 | Production: DNS `accounts`, Caddy block, Resend domain verification, first deploy | pending |
| 5 | Migrate apps, one PR each, in order: 3m4 shortener → exp → retro → metrics → smart-docs → bubbles. Each: verify the JWT, provision the local user from the claims, drop the local password tables, redirect `/login` + `/signup`, avatar + handle in the nav, global logout | pending |
| 6 | Static sites: `session.js` on info (login / logout / signup section), kinegram and bubbles (optional login, leaderboard with the shared identity) | pending |
| 7 | Later: Facebook login, account deletion / data export, passkeys | backlog |

## Non-goals (phase 1)

Plans, billing, API keys, MCP server, usage metering, organisations / teams.
Those stay inside each app.
