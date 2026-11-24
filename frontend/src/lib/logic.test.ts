import { marksFor } from "../components/Bubbles";
import { topicBreakdown } from "../pages/AttemptReview";
import type { Attempt } from "../api";
import { formatClock, relativeFromNow } from "./format";

const choices = ["A", "B", "C", "D"].map((id) => ({ id, text: id }));

test("marks: wrong pick and the correct answer", () => {
  expect(marksFor(choices, ["A"], ["B"])).toEqual({ A: "wrong", B: "correct" });
});

test("marks: multi-answer shows a missed correct choice", () => {
  expect(marksFor(choices, ["A"], ["A", "C"])).toEqual({ A: "correct", C: "missed" });
});

test("clock formatting", () => {
  expect(formatClock(0)).toBe("0:00");
  expect(formatClock(599)).toBe("9:59");
  expect(formatClock(3725)).toBe("1:02:05");
  expect(formatClock(-5)).toBe("0:00");
});

test("relative due time", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  expect(relativeFromNow("2026-01-01T00:10:00Z", now)).toBe("in 10 min");
  expect(relativeFromNow("2026-01-04T00:00:00Z", now)).toBe("in 3 days");
});

test("topic breakdown sorts weakest first", () => {
  const entry = (topic: string, correct: boolean) => ({
    item: { id: Math.random().toString(), type: "mcq_single", prompt: "", answer: {}, topics: [topic] },
    response: { correct } as never,
  });
  const a = {
    topicNames: { x: "X", y: "Y" },
    items: [entry("x", true), entry("x", true), entry("y", false), entry("y", true)],
  } as unknown as Attempt;
  expect(topicBreakdown(a)).toEqual([
    { name: "Y", correct: 1, total: 2 },
    { name: "X", correct: 2, total: 2 },
  ]);
});

test("only http(s) resource links are rendered", async () => {
  const { isWebUrl } = await import("../components/Feedback");
  expect(isWebUrl("https://docs.aws.amazon.com/")).toBe(true);
  expect(isWebUrl("javascript:alert(1)")).toBe(false);
  expect(isWebUrl(" javascript:alert(1)")).toBe(false);
  expect(isWebUrl("not a url")).toBe(false);
});
