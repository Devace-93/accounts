import { test, expect } from "@playwright/test";
import { PASSWORD, currentSession, tokenOf, uniqueEmail, waitForLink } from "../helpers";

/**
 * The hosted /signup page: handle derived from the email, show/hide toggles on
 * both password fields, confirm-password mismatch, then the full flow: sign up
 * → /profile (unverified) → verification mail → /verify?token= → badge.
 */
test.describe("signup", () => {
  test("derives the handle from the email and toggles both password fields", async ({ page }) => {
    const { email, handle } = uniqueEmail();
    await page.goto("/signup");

    await page.getByTestId("email").fill(email);
    // Prefilled from the local part as you type; still editable.
    await expect(page.getByTestId("handle")).toHaveValue(handle);
    await page.getByTestId("handle").fill(`${handle}x`);
    await expect(page.getByTestId("handle")).toHaveValue(`${handle}x`);

    const password = page.getByTestId("password");
    const confirm = page.getByTestId("password-confirm");
    const toggles = page.getByTestId("toggle-password");
    await expect(toggles).toHaveCount(2);

    await password.fill(PASSWORD);
    await confirm.fill(PASSWORD);
    await expect(password).toHaveAttribute("type", "password");
    await expect(confirm).toHaveAttribute("type", "password");

    // Each field has its own toggle.
    await toggles.nth(0).click();
    await expect(password).toHaveAttribute("type", "text");
    await expect(confirm).toHaveAttribute("type", "password");
    await toggles.nth(1).click();
    await expect(confirm).toHaveAttribute("type", "text");
    await toggles.nth(0).click();
    await expect(password).toHaveAttribute("type", "password");
    await expect(confirm).toHaveAttribute("type", "text");
  });

  test("refuses mismatching passwords without calling the API", async ({ page }) => {
    const { email } = uniqueEmail();
    const calls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/auth/signup")) calls.push(req.url());
    });

    await page.goto("/signup");
    await page.getByTestId("email").fill(email);
    await page.getByTestId("password").fill(PASSWORD);
    await page.getByTestId("password-confirm").fill(`${PASSWORD}-different`);
    // The mismatch is reported inline and the submit button stays disabled, so
    // the form can never reach the API (pressing Enter is a no-op too).
    await expect(page.getByText(/match/i).first()).toBeVisible();
    await expect(page.getByTestId("submit")).toBeDisabled();
    await page.getByTestId("password-confirm").press("Enter");
    await expect(page).toHaveURL(/\/signup\/?(\?.*)?$/);
    expect(calls).toEqual([]);
  });

  test("@critical sign up, land on the profile unverified, verify through the mailed link", async ({ page }) => {
    const { email, handle } = uniqueEmail();
    const started = new Date();

    await page.goto("/signup");
    await page.getByTestId("email").fill(email);
    await page.getByTestId("password").fill(PASSWORD);
    await page.getByTestId("password-confirm").fill(PASSWORD);
    await page.getByTestId("submit").click();

    await expect(page).toHaveURL(/\/profile\/?(\?.*)?$/);
    await expect(page.getByTestId("handle")).toHaveValue(handle);
    // Unverified: the banner with the resend button shows, the badge does not.
    await expect(page.getByTestId("resend-verification")).toBeVisible();
    await expect(page.getByTestId("verified-badge")).toHaveCount(0);

    const me = await currentSession(page.request);
    expect(me?.email).toBe(email);
    expect(me?.email_verified).toBe(false);

    // The verification mail carries a /verify?token= link; the page consumes it.
    const link = await waitForLink(email, "verify", { after: started });
    expect(tokenOf(link).length).toBeGreaterThan(20);
    await page.goto(link);
    await expect(page.getByText(/verified/i).first()).toBeVisible();

    await page.goto("/profile");
    await expect(page.getByTestId("verified-badge")).toBeVisible();
    await expect(page.getByTestId("resend-verification")).toHaveCount(0);
    expect((await currentSession(page.request))?.email_verified).toBe(true);
  });

  test("rejects a taken email and a reserved handle", async ({ page, request }) => {
    const { email } = uniqueEmail();
    // Take the email first through the API.
    const first = await request.post("/api/auth/signup", { data: { email, password: PASSWORD } });
    expect(first.status()).toBe(201);

    await page.goto("/signup");
    await page.getByTestId("email").fill(email);
    await page.getByTestId("password").fill(PASSWORD);
    await page.getByTestId("password-confirm").fill(PASSWORD);
    await page.getByTestId("submit").click();
    await expect(page.getByTestId("error")).toBeVisible();
    await expect(page).toHaveURL(/\/signup\/?(\?.*)?$/);

    const other = uniqueEmail();
    await page.getByTestId("email").fill(other.email);
    await page.getByTestId("handle").fill("admin");
    await page.getByTestId("submit").click();
    await expect(page.getByTestId("error")).toBeVisible();
    await expect(page).toHaveURL(/\/signup\/?(\?.*)?$/);
  });
});
