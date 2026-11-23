import { expect, test } from "@playwright/test";

const shots = process.env.E2E_SHOTS;
const snap = async (page: import("@playwright/test").Page, name: string) => {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
};

test("confidence ratings feed the review, progress report and topic drill", async ({ page }) => {
  await page.goto("/");
  await page.locator(".pack-row", { hasText: "Section 3 Quiz 1" }).getByRole("button", { name: "Practice" }).click();

  await expect(page.getByText("Question 1 of 10")).toBeVisible();
  // Q1 key is C: answer it, sure. Q2 key is B: answer A, also sure (confidently wrong).
  await page.keyboard.press("c");
  await page.keyboard.press("s");
  await expect(page.getByRole("radio", { name: "Sure", exact: true })).toHaveAttribute("aria-checked", "true");
  await snap(page, "08-confidence");
  await page.keyboard.press("Enter");
  await expect(page.locator(".feedback")).toContainText("Correct");
  await expect(page.getByText("You were sure.")).toBeVisible();
  await page.keyboard.press("Enter");
  await page.keyboard.press("a");
  await page.getByRole("radio", { name: "Sure", exact: true }).click();
  await page.keyboard.press("Enter");
  await expect(page.locator(".feedback")).toContainText("Not quite");

  await page.getByRole("button", { name: "End practice now and see results" }).click();
  await expect(page.getByText("1 of 10 correct")).toBeVisible();
  await page.getByRole("tab", { name: "Sure but wrong (1)" }).click();
  await expect(page.locator(".review-item")).toHaveCount(1);
  await expect(page.locator(".review-item .question-meta")).toContainText("Sure");

  await page.getByRole("link", { name: "Progress" }).click();
  const tab = page.getByRole("tab", { name: "Databricks Certified Machine Learning Associate" });
  if (await tab.count()) await tab.click();
  await expect(page.getByText("Estimated exam score")).toBeVisible();
  await expect(page.getByText("Early estimate")).toBeVisible();
  const row = page.getByRole("row", { name: /Model Development/ });
  await expect(row).toContainText("31%"); // share of exam
  await expect(page.getByRole("img", { name: /Scores for your last/ })).toBeVisible();
  await expect(page.getByText("When sure")).toBeVisible();
  await expect(page.getByRole("button", { name: /Practice sure-but-wrong/ })).toBeVisible();
  await snap(page, "09-progress");

  await row.getByRole("button", { name: /Drill/ }).click();
  await expect(page.getByRole("heading", { name: "Drill: Model Development" })).toBeVisible();
  await expect(page.getByText("Question 1 of 10")).toBeVisible();
});
