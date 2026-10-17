import { test, expect, type Page } from "@playwright/test";
import { BASE_URL } from "../playwright.config";
import { JWKS_URL, WIDGET_URL, currentSession, login, signup } from "../helpers";

/**
 * What relying apps and static sites consume: the JWKS, the widget's headers,
 * and the widget rendered on a host page served from another localhost origin
 * (the shape of info.3m4.net / kinegram / bubbles embedding session.js).
 */

/** Another localhost port: allowed by ALLOWED_ORIGINS and same-site for the cookie. */
const HOST_ORIGIN = "http://localhost:4321";

async function serveHost(page: Page): Promise<void> {
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Host site</title></head>
<body>
  <h1>Host site</h1>
  <div id="session"></div>
  <script src="${WIDGET_URL}" data-mount="#session" defer></script>
</body></html>`;
  await page.route(`${HOST_ORIGIN}/**`, (route) => route.fulfill({ status: 200, contentType: "text/html", body: html }));
  await page.goto(`${HOST_ORIGIN}/index.html`);
}

test.describe("session plumbing", () => {
  test("@critical publishes an Ed25519 JWKS", async ({ request }) => {
    const res = await request.get(JWKS_URL);
    expect(res.status()).toBe(200);
    expect(res.headers()["cache-control"]).toMatch(/max-age=\d+/);
    const body = await res.json();
    expect(Array.isArray(body.keys)).toBe(true);
    expect(body.keys.length).toBeGreaterThan(0);
    const key = body.keys[0];
    expect(key).toMatchObject({ kty: "OKP", crv: "Ed25519", alg: "EdDSA", use: "sig" });
    expect(typeof key.kid).toBe("string");
    expect(key.kid.length).toBeGreaterThan(0);
    expect(typeof key.x).toBe("string");
    expect(key.x.length).toBeGreaterThan(0);
    // No private material ever leaks into the key set.
    expect(key.d).toBeUndefined();
  });

  test("serves session.js cacheable and CORS-open", async ({ request }) => {
    const res = await request.get(WIDGET_URL);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/javascript/);
    expect(res.headers()["access-control-allow-origin"]).toBe("*");
    expect(res.headers()["cache-control"]).toMatch(/max-age=\d+/);
    expect((await res.text()).length).toBeGreaterThan(200);
  });

  test("GET /api/session answers 401 no_session without cookies and sets credentialed CORS headers", async ({ request }) => {
    const res = await request.get("/api/session", { headers: { Origin: HOST_ORIGIN } });
    expect(res.status()).toBe(401);
    expect((await res.json()).error.code).toBe("no_session");
    expect(res.headers()["access-control-allow-origin"]).toBe(HOST_ORIGIN);
    expect(res.headers()["access-control-allow-credentials"]).toBe("true");

    const foreign = await request.get("/api/session", { headers: { Origin: "https://evil.example" } });
    expect(foreign.headers()["access-control-allow-origin"]).toBeUndefined();
  });

  test("@critical the widget on a host page: signed out, then signed in", async ({ page, request }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await serveHost(page);
    await page.waitForFunction(() => typeof (window as any).m4session?.get === "function");
    const widget = page.locator("#session");
    await expect(widget.getByRole("link", { name: /log in/i })).toBeVisible();
    await expect(widget.getByRole("link", { name: /sign up/i })).toBeVisible();
    const loginHref = await widget.getByRole("link", { name: /log in/i }).getAttribute("href");
    expect(loginHref).toContain(`${BASE_URL}/login`);
    expect(loginHref).toContain(encodeURIComponent(`${HOST_ORIGIN}/index.html`));
    expect(await page.evaluate(() => (window as any).m4session.get())).toBeNull();

    // Sign in (cookies land in this browser context), reload the host page.
    const { email, handle } = await signup(page.request);
    await login(page.request, email);
    await page.reload();
    await page.waitForFunction(() => typeof (window as any).m4session?.get === "function");
    await expect(widget.getByText(handle)).toBeVisible();
    await expect(widget.getByRole("img")).toHaveAttribute("src", /\/avatars\//);
    const user = await page.evaluate(() => (window as any).m4session.get());
    expect(user?.handle).toBe(handle);

    // Menu: Profile + Log out. Logging out from the host page ends the session.
    await widget.getByText(handle).click();
    // The menu entries carry role="menuitem" (an anchor and a button).
    await expect(widget.getByRole("menuitem", { name: /profile/i })).toHaveAttribute("href", new RegExp(`${BASE_URL}/profile`));
    await widget.getByRole("menuitem", { name: /log out/i }).click();
    await expect(widget.getByRole("link", { name: /log in/i })).toBeVisible();
    expect(await currentSession(page.request)).toBeNull();
    expect(errors).toEqual([]);
  });

  test("the widget never throws into the host page when the API is unreachable", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route(`${BASE_URL}/api/session`, (route) => route.abort("connectionrefused"));
    await serveHost(page);
    await page.waitForFunction(() => typeof (window as any).m4session?.get === "function");
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => (window as any).m4session.get())).toBeNull();
    expect(errors).toEqual([]);
  });
});
