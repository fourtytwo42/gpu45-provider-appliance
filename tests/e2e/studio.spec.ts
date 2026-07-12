import { expect, test } from "@playwright/test";

for (const [route, heading] of [
  ["/studio/speech", "Speech"],
  ["/studio/audiobooks", "Audiobooks"],
  ["/studio/presentations", "Presentations"],
  ["/studio/voices", "Voice Library"],
  ["/studio/training", "Training"],
] as const) {
  test(`${heading} workflow mounts independently`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(route);
    await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  });
}

test("legacy TTS route redirects to Speech", async ({ page }) => {
  await page.goto("/tts");
  await expect(page).toHaveURL(/\/studio\/speech$/);
});
