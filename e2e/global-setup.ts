/**
 * Wait for the API and warm the SSR server before the suite: the first
 * requests after a container (re)build are slow enough to race the sign-up
 * flow. One GET per entry page.
 */
import { BASE_URL, MAILPIT_URL } from "./playwright.config";

async function waitFor(url: string, ok: (res: Response) => boolean, attempts = 60): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const res = await fetch(url);
      if (ok(res)) return;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${url} did not become ready`);
}

export default async function globalSetup(): Promise<void> {
  await waitFor(`${BASE_URL}/api/healthz`, (res) => res.ok);
  await waitFor(`${MAILPIT_URL}/api/v1/info`, (res) => res.ok, 15).catch(() => {
    console.warn(`Mailpit not reachable at ${MAILPIT_URL}: the mail-driven specs will fail`);
  });
  for (const path of ["/", "/login/", "/signup/", "/magic/", "/profile/", "/session.js", "/.well-known/jwks.json"]) {
    await waitFor(BASE_URL + path, (res) => res.status < 500, 10).catch(() => {});
  }
}
