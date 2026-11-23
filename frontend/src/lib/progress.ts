import type { ExamStats, ReadinessStatus } from "../api";

export const STATUS_LABEL: Record<ReadinessStatus, string> = {
  on_track: "On track to pass",
  borderline: "Close to the passing line",
  below: "Below the passing line",
  early: "Early estimate",
  no_topics: "No estimate yet",
};

/** One sentence explaining the estimate and what would make it better. */
export function readinessAdvice(s: ExamStats): string {
  const r = s.readiness;
  if (r.status === "no_topics") return "This exam's questions have no topics yet, so there's nothing to weigh.";
  const untested = s.topics.filter((t) => t.seen < 3).map((t) => t.name);
  if (r.status === "early") {
    if (r.answered < 20) return `Based on ${r.answered} answer${r.answered === 1 ? "" : "s"}. Answer at least 20 for a steadier number.`;
    return `Not enough practice yet in ${listNames(untested)}. Topics you haven't tried count as a coin flip.`;
  }
  const weak = s.topics.filter((t) => s.weakTopics.includes(t.id)).map((t) => t.name);
  if (r.status === "on_track") return weak.length ? `Keep it there. Your softest area is ${listNames(weak)}.` : "Keep it there.";
  return `Most to gain from ${listNames(weak)}.`;
}

export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** Share of the exam as a whole-number percent, or null when the blueprint gives no weights. */
export function weightPercent(w: number | null | undefined): number | null {
  return w ? Math.round(w * 100) : null;
}
