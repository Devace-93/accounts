import { test, expect, type Page } from "@playwright/test";
import { WIDGET_URL } from "../helpers";

/**
 * Language continuity: a relying site hands its locale over with `?lang=` on
 * the hosted pages (CONTRACT.md → Hosted pages). Checks that a valid value is
 * honoured and persisted, that a bad one is ignored, that the hops between
 * the hosted pages keep it, and that session.js sends the host's `3m4.lang`.
 */

/** Another localhost port: allowed by ALLOWED_ORIGINS and same-site for the cookie. */
const HOST_ORIGIN = "http://localhost:4321";

async function serveHost(page: Page, lang: string): Promise<void> {
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Host site</title>
<script>localStorage.setItem("3m4.lang", ${JSON.stringify(lang)});</script></head>
<body><div id="session"></div>
<script src="${WIDGET_URL}" data-mount="#session" defer></script>
</body></html>`;
  await page.route(`${HOST_ORIGIN}/**`, (route) => route.fulfill({ status: 200, contentType: "text/html", body: html }));
  await page.goto(`${HOST_ORIGIN}/index.html`);
}

test.describe("lang query parameter", () => {
  test("opens the page in the requested locale, persists it and carries it to the next hop", async ({ page }) => {
    await page.goto("/login?lang=es-MX&return_to=https%3A%2F%2Finfo.3m4.net%2F");
    await expect(page.locator("html")).toHaveAttribute("lang", "es-MX");
    await expect(page.getByTestId("submit")).toHaveText(/Iniciar sesión/);
    expect(await page.evaluate(() => localStorage.getItem("3m4.lang"))).toBe("es-MX");
    const signup = page.getByRole("link", { name: /Regístrate|Crear cuenta|Sign up/i }).first();
    await expect(signup).toHaveAttribute("href", /lang=es-MX/);
    await expect(signup).toHaveAttribute("href", /return_to=https%3A%2F%2Finfo\.3m4\.net/);
  });

  test("maps a base language or unlisted variant to the first locale of that language", async ({ page }) => {
    await page.goto("/login?lang=pt");
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
    await page.goto("/login?lang=es-UY");
    await expect(page.locator("html")).toHaveAttribute("lang", "es-MX");
  });

  test("ignores an unknown value silently and keeps the saved choice", async ({ page }) => {
    await page.goto("/login?lang=de-DE");
    await expect(page.locator("html")).toHaveAttribute("lang", "de-DE");
    await page.goto("/login?lang=zz-ZZ");
    await expect(page.locator("html")).toHaveAttribute("lang", "de-DE");
    expect(await page.evaluate(() => localStorage.getItem("3m4.lang"))).toBe("de-DE");
    await page.goto("/login?lang=%3Cscript%3E");
    await expect(page.locator("html")).toHaveAttribute("lang", "de-DE");
    await expect(page.getByTestId("submit")).toBeVisible();
  });

  test("session.js hands the host's 3m4.lang over to the hosted pages", async ({ page }) => {
    await serveHost(page, "fr-FR");
    const login = page.locator('[data-m4s="login"]');
    await expect(login).toBeVisible();
    await expect(login).toHaveAttribute("href", /\/login\?return_to=.*&lang=fr-FR$/);
    await expect(page.locator('[data-m4s="signup"]')).toHaveAttribute("href", /\/signup\?return_to=.*&lang=fr-FR$/);
    await login.click();
    await expect(page).toHaveURL(/\/login\/?\?.*lang=fr-FR/);
    await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  });
});
