import { test, expect, type Page } from "@playwright/test";
import { BASE_URL } from "../playwright.config";
import { PASSWORD, currentSession, loginViaUi, signup } from "../helpers";

/**
 * The hosted /login page and the session it creates: wrong password, success,
 * `return_to` (honoured for an allowed origin, ignored for a foreign one) and
 * log out from the profile page.
 */

/** A pretend relying app on another localhost port (allowed by ALLOWED_ORIGINS). */
const APP_ORIGIN = "http://localhost:4321";
const EVIL_ORIGIN = "https://evil.example";

async function stubOrigin(page: Page, origin: string, title: string): Promise<void> {
  await page.route(`${origin}/**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: `<!doctype html><html><head><title>${title}</title></head><body><h1>${title}</h1></body></html>`,
    }),
  );
}

test.describe("login", () => {
  test("rejects a wrong password and stays on the page", async ({ page, request }) => {
    const { email } = await signup(request);
    await loginViaUi(page, email, "definitely-wrong-1");
    await expect(page.getByTestId("error")).toBeVisible();
    await expect(page.getByTestId("error")).toHaveText(/incorrect|invalid|wrong/i);
    await expect(page).toHaveURL(/\/login\/?(\?.*)?$/);
    expect(await currentSession(page.request)).toBeNull();
  });

  test("@critical logs in, lands on the profile, logs out everywhere", async ({ page, request }) => {
    const { email, handle } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);
    await expect(page.getByTestId("handle")).toHaveValue(handle);
    expect((await currentSession(page.request))?.handle).toBe(handle);

    await page.getByTestId("logout").click();
    await expect(page).toHaveURL(/\/login\/?(\?.*)?$/);
    expect(await currentSession(page.request)).toBeNull();

    // The profile is guarded again.
    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login\/?(\?.*)?$/);
  });

  test("honours return_to for an allowed origin", async ({ page, request }) => {
    const { email } = await signup(request);
    await stubOrigin(page, APP_ORIGIN, "Relying app");
    const target = `${APP_ORIGIN}/dashboard?tab=links`;

    await loginViaUi(page, email, PASSWORD, target);
    await expect(page).toHaveURL(target);
    await expect(page.getByRole("heading", { name: "Relying app" })).toBeVisible();
  });

  test("ignores return_to for a foreign origin", async ({ page, request }) => {
    const { email } = await signup(request);
    await stubOrigin(page, EVIL_ORIGIN, "Evil");

    await loginViaUi(page, email, PASSWORD, `${EVIL_ORIGIN}/steal`);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);
    expect(page.url().startsWith(BASE_URL)).toBe(true);
  });

  test("a signed-in visitor of /login is sent straight to return_to", async ({ page, request }) => {
    const { email } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);

    await stubOrigin(page, APP_ORIGIN, "Relying app");
    await page.goto(`/login?return_to=${encodeURIComponent(`${APP_ORIGIN}/`)}`);
    await expect(page).toHaveURL(`${APP_ORIGIN}/`);
  });
});
