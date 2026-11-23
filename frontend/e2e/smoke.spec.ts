import { expect, test } from "@playwright/test";

const shots = process.env.E2E_SHOTS; // directory for review screenshots, optional
const snap = async (page: import("@playwright/test").Page, name: string) => {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
};

test("timed exam: answer, submit, review explains the miss", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Databricks Certified Machine Learning Associate" })).toBeVisible();
  await snap(page, "01-library");

  const row = page.locator(".pack-row", { hasText: "Section 1 Quiz 1" });
  await row.getByRole("button", { name: "Timed" }).click();
  await expect(page.getByRole("timer")).toBeVisible();
  await expect(page.getByText("Question 1 of 10")).toBeVisible();

  // Q1 key is B: pick A (wrong) with the keyboard. Q2 key is D: pick it by clicking.
  await page.keyboard.press("a");
  await expect(page.locator(".sheet-cell").first()).toHaveClass(/is-answered/);
  await page.getByRole("button", { name: "Next question" }).click();
  await page.getByText("Each trial generates a notebook").click();
  await page.keyboard.press("f"); // flag Q2
  await expect(page.getByText("Flagged for review", { exact: true })).toBeVisible();
  await snap(page, "02-exam");

  await page.locator(".sheet-cell").last().click();
  await page.getByRole("button", { name: "Review and submit" }).click();
  await expect(page.getByRole("dialog")).toContainText("8 questions are unanswered");
  await snap(page, "03-confirm");
  await page.getByRole("button", { name: "Submit exam" }).click();

  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByText("1 of 10 correct")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Missed (9)" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".review-item").first()).toContainText("Your answer");
  await expect(page.locator(".review-item").first()).toContainText("Correct answer");
  await expect(page.locator(".feedback").first()).toContainText("Not quite");
  await snap(page, "04-review");

  await page.getByRole("tab", { name: "Flagged (1)" }).click();
  await expect(page.locator(".review-item")).toHaveCount(1);
});

test("practice mode gives feedback per question, then retake missed", async ({ page }) => {
  await page.goto("/");
  await page.locator(".pack-row", { hasText: "Section 2 Quiz 1" }).getByRole("button", { name: "Practice" }).click();
  await expect(page.getByRole("button", { name: "Check answer" })).toBeDisabled();
  await page.keyboard.press("c"); // Q1 key is C
  await page.keyboard.press("Enter");
  await expect(page.locator(".feedback")).toContainText("Correct");
  await page.keyboard.press("Enter");
  await page.keyboard.press("a"); // Q2 key is D
  await page.keyboard.press("Enter");
  await expect(page.locator(".feedback")).toContainText("Not quite");
  await expect(page.locator(".bubble-row.is-correct")).toContainText("Correct answer");
  await snap(page, "05-practice");

  await page.getByRole("button", { name: "End practice now and see results" }).click();
  await expect(page.getByText("1 of 10 correct")).toBeVisible();
  await page.getByRole("button", { name: "Retake 9 missed" }).click();
  await expect(page.getByText("Question 1 of 9")).toBeVisible();
});

test("flashcards: reveal and rate", async ({ page }) => {
  await page.goto("/");
  const row = page.locator(".pack-row", { hasText: "Domain 2" });
  await row.getByRole("button", { name: /Flashcards/ }).click();
  // 26 cards in the deck, but a session introduces at most 20 new ones
  await expect(page.getByText(/20 cards left/)).toBeVisible();
  await snap(page, "06-card-front");
  await page.keyboard.press(" ");
  await expect(page.getByRole("group", { name: "How well did you remember?" })).toBeVisible();
  await snap(page, "07-card-back");
  await page.keyboard.press("3");
  await expect(page.getByText(/19 cards left/)).toBeVisible();
  await page.keyboard.press(" ");
  await page.getByRole("button", { name: /Again/ }).click();
  await expect(page.getByText(/19 cards left/)).toBeVisible(); // "Again" requeues the card
});
