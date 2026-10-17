import { test, expect } from "@playwright/test";
import { BASE_URL } from "../playwright.config";
import { PASSWORD, TINY_PNG, currentSession, login, loginViaUi, signup, uniqueHandle } from "../helpers";

/**
 * The /profile page: name + handle edits, avatar upload / removal (served as
 * WebP, then back to the generated SVG), password change revoking the other
 * sessions, and the session list.
 */
test.describe("profile", () => {
  test("@critical edits the name and the handle", async ({ page, request }) => {
    const { email } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);

    const handle = uniqueHandle("renamed");
    await page.getByTestId("name").fill("Ana López");
    await page.getByTestId("handle").fill(handle);
    // Wait for the PATCH to land before reading the session back.
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/me") && r.request().method() === "PATCH"),
      page.getByTestId("save-profile").click(),
    ]);

    await expect(page.getByTestId("error")).toHaveCount(0);
    const me = await currentSession(page.request);
    expect(me?.name).toBe("Ana López");
    expect(me?.handle).toBe(handle);

    await page.reload();
    await expect(page.getByTestId("name")).toHaveValue("Ana López");
    await expect(page.getByTestId("handle")).toHaveValue(handle);

    // A reserved handle is refused inline.
    await page.getByTestId("handle").fill("admin");
    await page.getByTestId("save-profile").click();
    await expect(page.getByTestId("error")).toBeVisible();
    expect((await currentSession(page.request))?.handle).toBe(handle);
  });

  test("uploads and removes the avatar", async ({ page, request }) => {
    const { email, user } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);

    // Default: the generated SVG.
    const before = await page.request.get(`${BASE_URL}/avatars/${user.id}`);
    expect(before.status()).toBe(200);
    expect(before.headers()["content-type"]).toContain("image/svg+xml");
    const srcBefore = await page.getByTestId("avatar-img").getAttribute("src");

    await page.getByTestId("avatar-input").setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: TINY_PNG });
    await expect
      .poll(async () => page.getByTestId("avatar-img").getAttribute("src"), { timeout: 15_000 })
      .not.toBe(srcBefore);
    const srcAfter = (await page.getByTestId("avatar-img").getAttribute("src"))!;
    expect(srcAfter).toContain(`/avatars/${user.id}`);

    const uploaded = await page.request.get(srcAfter.startsWith("http") ? srcAfter : `${BASE_URL}${srcAfter}`);
    expect(uploaded.status()).toBe(200);
    expect(uploaded.headers()["content-type"]).toContain("image/webp");
    expect(uploaded.headers()["cache-control"]).toMatch(/max-age=\d+/);
    const me = await currentSession(page.request);
    expect(me?.avatar_url).toContain(`/avatars/${user.id}`);
    expect(me?.avatar_url).not.toBe(user.avatar_url);

    await page.getByTestId("avatar-remove").click();
    await expect
      .poll(async () => {
        const res = await page.request.get(`${BASE_URL}/avatars/${user.id}?v=${Date.now()}`);
        return res.headers()["content-type"] ?? "";
      })
      .toContain("image/svg+xml");
  });

  test("changing the password revokes the other sessions", async ({ page, request, browser }) => {
    const { email } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);

    // A second device, logged in before the change.
    const other = await browser.newContext();
    try {
      await login(other.request, email);
      expect((await currentSession(other.request))?.email).toBe(email);
      await expect(page.getByTestId("session-row")).toHaveCount(2);

      const newPassword = `${PASSWORD}-changed`;
      await page.getByTestId("password-current").fill(PASSWORD);
      await page.getByTestId("password").fill(newPassword);
      await page.getByTestId("password-confirm").fill(newPassword);
      // Wait for the PUT to land before probing the other session.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/api/me/password") && r.request().method() === "PUT"),
        page.getByTestId("save-password").click(),
      ]);
      await expect(page.getByTestId("error")).toHaveCount(0);

      // This session survives…
      expect((await currentSession(page.request))?.email).toBe(email);
      // …the other one cannot refresh any more.
      const refresh = await other.request.post("/api/session/refresh", { data: {} });
      expect(refresh.status()).toBe(401);

      // Old password is gone, new one works.
      const old = await other.request.post("/api/auth/login", { data: { email, password: PASSWORD } });
      expect(old.status()).toBe(401);
      await login(other.request, email, newPassword);
    } finally {
      await other.close();
    }
  });

  test("log out everywhere ends every session", async ({ page, request, browser }) => {
    const { email } = await signup(request);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);

    const other = await browser.newContext();
    try {
      // signup() + loginViaUi() already opened two sessions; the other context adds a third.
      await login(other.request, email);
      await page.reload();
      await expect(page.getByTestId("session-row")).toHaveCount(3);

      await page.getByTestId("logout-all").click();
      await expect(page).toHaveURL(/\/login\/?(\?.*)?$/);
      expect(await currentSession(page.request)).toBeNull();
      expect((await other.request.post("/api/session/refresh", { data: {} })).status()).toBe(401);
    } finally {
      await other.close();
    }
  });
});
