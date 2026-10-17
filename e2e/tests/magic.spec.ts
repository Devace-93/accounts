import { test, expect } from "@playwright/test";
import { currentSession, signup, tokenOf, uniqueEmail, waitForLink } from "../helpers";

/**
 * Passwordless login: request a magic link from /login, read it from Mailpit,
 * open it (the /magic page POSTs the token), end up signed in and verified.
 * A second use of the same link fails.
 */
test.describe("magic link", () => {
  test("@critical requests a link, consumes it, cannot reuse it", async ({ page, request }) => {
    const { email } = await signup(request);
    const started = new Date();

    await page.goto("/login");
    await page.getByTestId("email").fill(email);
    // The CTA hands the typed email over to /magic; sending is an explicit click there.
    await page.getByTestId("magic-link").click();
    await expect(page).toHaveURL(/\/magic\/?\?/);
    await expect(page.getByTestId("email")).toHaveValue(email);
    await page.getByTestId("submit").click();
    // The request form answers 202 whatever the email; the page says "check your inbox".
    await expect(page.getByText(/inbox|sent|check your/i).first()).toBeVisible();

    const link = await waitForLink(email, "magic", { after: started });
    const token = tokenOf(link);

    // This browser context has no session yet.
    expect(await currentSession(page.request)).toBeNull();

    await page.goto(link);
    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);
    const me = await currentSession(page.request);
    expect(me?.email).toBe(email);
    expect(me?.email_verified).toBe(true);

    // Reuse: the API refuses the burnt token.
    const again = await request.post("/api/auth/magic/consume", { data: { token } });
    expect(again.status()).toBe(400);
    expect((await again.json()).error.code).toBe("used_token");

    // And the page shows the error with a way to request a new one.
    await page.context().clearCookies();
    await page.goto(link);
    await expect(page.getByTestId("error")).toBeVisible();
    await expect(page.getByTestId("email")).toBeVisible();
  });

  test("answers 202 for an unknown email and does not reveal it", async ({ page, request }) => {
    const { email } = uniqueEmail("nobody");
    const res = await request.post("/api/auth/magic", { data: { email } });
    expect(res.status()).toBe(202);

    await page.goto("/magic");
    await page.getByTestId("email").fill(email);
    await page.getByTestId("submit").click();
    await expect(page.getByText(/inbox|sent|check your/i).first()).toBeVisible();
    await expect(page.getByTestId("error")).toHaveCount(0);
  });

  test("a garbage token is rejected", async ({ request }) => {
    const res = await request.post("/api/auth/magic/consume", { data: { token: "not-a-real-token" } });
    expect(res.status()).toBe(400);
    expect((await res.json()).error.code).toBe("invalid_token");
  });
});
