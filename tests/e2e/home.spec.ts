import { expect, test } from "@playwright/test";

test("home dashboard renders", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/");
  await expect(page.getByText("GPU45 Appliance")).toBeVisible();
  await expect(page.getByText("Thermal envelope")).toBeVisible();
  await expect(page.getByText("Inference activity")).toBeVisible();
  await expect(page.getByText("Memory pressure")).toBeVisible();
  await expect(page.getByText("Power and cooling")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});
