import type { Attempt, ExamStats } from "../api";
import { missedResources } from "../pages/AttemptReview";
import { listNames, readinessAdvice, weightPercent } from "./progress";

const topic = (id: string, name: string, seen: number) => ({
  id, name, weight: 0.5, itemCount: 10, seen, answered: seen, correct: 0, mastery: 0.5, trend: [],
});

function stats(over: Partial<ExamStats["readiness"]>, seen = [5, 5]): ExamStats {
  return {
    exam: "x", name: "X", questionCount: 20, untopicedCount: 0,
    readiness: { score: 0.6, coverage: 1, answered: 40, passingScore: 0.7, status: "below", ...over },
    topics: [topic("a", "Alpha", seen[0]), topic("b", "Beta", seen[1])],
    weakTopics: ["b"], trend: [],
    calibration: { levels: [], unrated: 0, confidentlyWrong: [], luckyGuesses: [] },
    missedCount: 0, resources: [], missedWithoutResources: 0, dueCount: 0,
  };
}

test("readiness advice names what to do next", () => {
  expect(readinessAdvice(stats({}))).toBe("Most to gain from Beta.");
  expect(readinessAdvice(stats({ status: "early", answered: 1 }))).toMatch(/Based on 1 answer\. /);
  expect(readinessAdvice(stats({ status: "early" }, [5, 0]))).toMatch(/Not enough practice yet in Beta/);
  expect(readinessAdvice(stats({ status: "on_track" }))).toBe("Keep it there. Your softest area is Beta.");
});

test("list names and weights", () => {
  expect(listNames(["A", "B", "C"])).toBe("A, B and C");
  expect(listNames(["A"])).toBe("A");
  expect(weightPercent(0.38)).toBe(38);
  expect(weightPercent(null)).toBeNull();
});

test("reading list collects links from misses only, most-cited first", () => {
  const link = (title: string) => ({ title, url: `https://docs.example.com/${title}` });
  const entry = (correct: boolean, resources: { title: string; url: string }[]) => ({
    item: { id: Math.random().toString(), type: "mcq_single", prompt: "", resources },
    response: { correct, choiceIds: [], text: null, flagged: false, confidence: null, timeMs: null, answered: true },
  });
  const a = {
    items: [
      entry(false, [link("b"), { title: "bad", url: "javascript:alert(1)" }]),
      entry(false, [link("a"), link("b")]),
      entry(true, [link("c")]),
    ],
  } as unknown as Attempt;
  expect(missedResources(a).map((r) => [r.title, r.count])).toEqual([["b", 2], ["a", 1]]);
});
