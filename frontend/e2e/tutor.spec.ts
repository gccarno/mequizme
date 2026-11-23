import { expect, test } from "@playwright/test";

const shots = process.env.E2E_SHOTS;
const snap = async (page: import("@playwright/test").Page, name: string) => {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
};

// Runs against the offline fake tutor (see backend/tests/e2e_server.py), so answers are canned.
test("AI tutor: drafts in practice, explain a mistake, chat, review and write questions", async ({ page, request }) => {
  const packs = await (await request.get("/api/packs")).json();
  const pack = packs.find((p: { name: string }) => p.name.includes("Section 4"));
  const job = await (await request.post("/api/ai/enrich", { data: { packId: pack.id } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/ai/jobs/${job.id}`)).json()).status, { timeout: 15_000 })
    .toBe("done");
  const full = await (await request.get(`/api/packs/${pack.id}`)).json();
  const first = full.items[0];
  const wrong = first.choices.find((c: { id: string }) => !first.answer.choiceIds.includes(c.id)).id;

  // Practice: the AI-written explanation is labelled, and the tutor can explain the miss.
  await page.goto("/");
  await page.locator(".pack-row", { hasText: "Section 4 Quiz 1" }).getByRole("button", { name: "Practice" }).click();
  await expect(page.getByText("Question 1 of 10")).toBeVisible();
  await page.keyboard.press(wrong.toLowerCase());
  await page.keyboard.press("Enter");
  await expect(page.locator(".feedback")).toContainText("Because of the concept.");
  await expect(page.locator(".draft-note")).toContainText("written by the AI tutor");
  await page.getByRole("button", { name: "Explain my mistake" }).click();
  await expect(page.locator(".tutor-note")).toContainText("Remember:");
  await page.getByRole("button", { name: "Ask the tutor about this question" }).click();
  await page.getByRole("textbox", { name: "Message to the tutor" }).fill("Why not my answer?");
  await page.keyboard.press("Enter"); // sends, and doesn't move to the next question
  await expect(page.locator(".chat-msg.is-assistant")).toContainText("Good question");
  await expect(page.getByText("Question 1 of 10")).toBeVisible();
  await snap(page, "20-tutor-practice");

  // Review drafts.
  await page.getByRole("link", { name: /AI tutor/ }).click();
  await expect(page.getByRole("heading", { name: "To review (10)" })).toBeVisible();
  await snap(page, "21-drafts");
  const cards = page.locator(".draft-card");
  await cards.first().getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByRole("heading", { name: "To review (9)" })).toBeVisible();

  await cards.first().getByRole("button", { name: "Edit" }).click();
  await cards.first().getByRole("textbox", { name: "Explanation" }).fill("My own explanation.");
  await snap(page, "22-draft-edit");
  await cards.first().getByRole("button", { name: "Save and accept" }).click();
  await expect(page.getByRole("heading", { name: "To review (8)" })).toBeVisible();
  const edited = await (await request.get(`/api/packs/${pack.id}`)).json();
  expect(edited.items.some((i: { explanation?: string }) => i.explanation === "My own explanation.")).toBe(true);

  await cards.first().getByRole("button", { name: "Reject" }).click();
  await expect(page.getByRole("heading", { name: "To review (7)" })).toBeVisible();

  // Write new questions: they arrive as drafts, outside quizzes until accepted.
  await page.getByLabel("Topic").selectOption({ label: "Model Deployment" });
  await page.getByLabel("How many").selectOption("3");
  await page.getByRole("button", { name: "Write 3 questions" }).click();
  await expect(page.getByText("Wrote 3 new questions on Model Deployment. Review below.")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "New questions (3)" }).click();
  await expect(cards).toHaveCount(3);
  await cards.first().getByRole("button", { name: "Delete question" }).click();
  await expect(cards).toHaveCount(2);
  await snap(page, "23-new-questions");
});
