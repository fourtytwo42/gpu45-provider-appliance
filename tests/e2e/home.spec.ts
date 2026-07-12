import { expect, test, type Page } from "@playwright/test";

async function expectHealthyHome(page: Page) {
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Ready for Codex|Ready on demand|Starting the LLM|Restoring the LLM|Appliance needs attention/ })).toBeVisible();
  await expect(page.getByText("Junction", { exact: true })).toBeVisible();
  await expect(page.getByText("VRAM", { exact: true })).toBeVisible();
  await expect(page.getByText("Power", { exact: true })).toBeVisible();
  await expect(page.getByText("Storage", { exact: true })).toBeVisible();
  await expect(page.getByText("Recent operating envelope")).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(hasHorizontalOverflow).toBe(false);
  expect(consoleErrors).toEqual([]);
}

test("home dashboard renders on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await expectHealthyHome(page);
});

test("home dashboard fits a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expectHealthyHome(page);
});
